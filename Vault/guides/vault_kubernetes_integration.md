# Интеграция Vault с Kubernetes через CSI Driver

## Определения

* **CSI (Container Storage Interface) Driver** — интерфейс для подключения внешних систем хранения данных к Kubernetes. **Secrets Store CSI Driver** монтирует секреты из Vault в поды как виртуальный том. Приложение видит секреты как обычные файлы, не взаимодействуя с Vault напрямую через API (Application Programming Interface).
* **CRD (Custom Resource Definition)** — механизм расширения API Kubernetes для создания собственных типов ресурсов.
* **SecretProviderClass** — ресурс (CRD), описывающий, какие именно секреты нужно извлечь из Vault и по какому пути.
* **JWT (JSON Web Token)** — стандарт для создания токенов доступа. Используется Kubernetes для аутентификации подов в Vault.

Стандартные Kubernetes `Secret` хранят данные в `etcd` в формате Base64 (не зашифровано по умолчанию). Для производственных (production) сред рекомендуется использовать внешнее специализированное хранилище — [HashiCorp Vault](../overview.md).

## Основные концепции

### Стратегии интеграции

| Подход | Описание | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **Vault Agent Sidecar** | Дополнительный контейнер (sidecar) в поде аутентифицируется в Vault, извлекает секреты и сохраняет их в `emptyDir` или передает в переменные окружения. Подробности — [sidecar_pattern.md](./vault_agent/sidecar_pattern.md). | Нет кластерных компонентов; поддержка динамической ротации с сигналом `SIGHUP` (Signal Hang Up) | Требует модификации каждого `Deployment`; неудобен для приложений, не умеющих перечитывать конфиг без перезапуска |
| **Vault Injector** | Автоматическое внедрение Vault Agent через Mutating Admission Webhook на основе аннотаций пода. Подробности — [injector.md](./vault_agent/injector.md). | Не требует ручной модификации манифестов приложений; централизованное управление | Зависимость от компонента Injector; меньше гибкости в конфигурации |
| **Secrets Store CSI Driver** | Кластерный драйвер монтирует секреты напрямую как тома (volumes). Идеален для использования в `initContainer` (контейнерах инициализации) для генерации конфигов до старта основного приложения. | Нативный подход для Kubernetes; универсальность (поддержка Vault, Azure Key Vault, GCP Secret Manager) | Требует установки CSI Driver и провайдера на весь кластер; сложнее в отладке |

### Аутентификация Vault через Kubernetes

Vault доверяет Kubernetes API через метод аутентификации `kubernetes`:

1. Под (Pod) использует токен своего `ServiceAccount` для аутентификации.
2. Vault проверяет подпись токена через Kubernetes Token Review API.
3. При совпадении параметров `bound_service_account_names` и `bound_service_account_namespaces` Vault выдаёт токен доступа с привязанной политикой.

Подробнее о механизмах — в [concepts.md](../concepts.md#методы-аутентификации-и-токены).

## Практические сценарии

### Шаг 1: Установка компонентов

**1. Vault через Helm** (режим HA — High Availability, PostgreSQL бэкенд):

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

### Шаг 2: Инициализация и распечатывание (Unseal)

После установки поды запущены, но находятся в состоянии `Sealed` (запечатаны). Процедуру Unseal необходимо выполнить для каждой реплики.

**1. Инициализация (выполняется один раз):**

```bash
kubectl exec -n vault vault-0 -- vault operator init -key-shares=1 -key-threshold=1 -format=json > cluster-keys.json
```

**2. Unseal каждой реплики:**

```bash
UNSEAL_KEY=$(jq -r ".unseal_keys_b64[0]" cluster-keys.json)
kubectl exec -n vault vault-0 -- vault operator unseal $UNSEAL_KEY
kubectl exec -n vault vault-1 -- vault operator unseal $UNSEAL_KEY
```

### Шаг 3: Настройка аутентификации Kubernetes

**1. Включение KV (Key-Value) v2 и Kubernetes auth:**

```bash
vault secrets enable -path=secret kv-v2
vault auth enable kubernetes
```

**2. Настройка связи с Kubernetes API:**

```bash
vault write auth/kubernetes/config \
   token_reviewer_jwt="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)" \
   kubernetes_host="https://kubernetes.default.svc" \
   kubernetes_ca_cert=@/var/run/secrets/kubernetes.io/serviceaccount/ca.crt
```

**3. Создание секрета, политики и роли:**

```bash
# Создание секрета
vault kv put secret/webapp/config username="db-user" password="Password123!"

# Определение политики
vault policy write webapp-policy - <<EOF
path "secret/data/webapp/config" {
  capabilities = ["read"]
}
EOF

# Создание роли (связь ServiceAccount с политикой)
vault write auth/kubernetes/role/webapp-role \
    bound_service_account_names=webapp-sa \
    bound_service_account_namespaces=default \
    policies=webapp-policy \
    ttl=24h
```

### Шаг 4: Развертывание приложения

**1. Манифест SecretProviderClass:**

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

**2. Deployment с использованием initContainer для генерации конфига:**

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
```

## Дополнительная информация

### Устранение неисправностей (Troubleshooting)

| Проблема | Решение |
| :--- | :--- |
| Под в состоянии `Pending` | Проверить `kubectl describe pod`. Установлен ли CSI Driver в кластере? |
| Секреты не монтируются в `/mnt/secrets` | Проверить логи `initContainer`; валидность `SecretProviderClass` и соответствие `roleName`. |
| Ошибка аутентификации в Vault | Убедиться, что `bound_service_account_names` и `namespace` в роли Vault совпадают с манифестом. |
| Требуется `unseal` после перезапуска | Выполнить unseal вручную или настроить Auto-unseal через KMS (Key Management Service) / HSM (Hardware Security Module). |

**См. также:**

* [Концепции HashiCorp Vault](../concepts.md)
* [Подход Zero Trust в Vault](../zero_trust.md)
* [CSI Driver в Kubernetes](../../Kubernetes/Storage/CSI/csi_overview.md)
