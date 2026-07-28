# Интеграция Vault с Kubernetes

## Определения

**Интеграция Vault с Kubernetes** — совокупность архитектурных паттернов и инструментов для обеспечения безопасности секретов в контейнеризированных средах. Основная цель — исключение хранения чувствительных данных в `etcd` в открытом виде и реализация модели динамического управления секретами.

**CSI (Container Storage Interface) Driver** — стандартный интерфейс для подключения систем хранения к Kubernetes. **Secrets Store CSI Driver** монтирует секреты из Vault напрямую в поды как виртуальный том (tmpfs). Приложение видит секреты как обычные файлы.

**Vault Secrets Operator (VSO)** — современный нативный контроллер Kubernetes, который синхронизирует секреты из Vault напрямую в объекты `Secret` Kubernetes или монтирует их, поддерживая автоматическую ротацию и интеграцию с нативными ресурсами через CRD.

**Vault Agent Injector** — механизм на основе Mutating Admission Webhook, который автоматически внедряет sidecar-контейнеры Vault Agent в поды для аутентификации и рендеринга секретов на основе аннотаций.

**CRD (Custom Resource Definition)** — механизм расширения API Kubernetes для создания собственных типов ресурсов (например, `SecretProviderClass` или `VaultStaticSecret`).

**JWT (JSON Web Token)** — стандарт токенов доступа, используемый Kubernetes для аутентификации подов (через ServiceAccount) в Vault.

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

**Установка через Helm (HA-режим с PostgreSQL):**

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

kubectl exec -n vault vault-0 -- vault operator unseal $UNSEAL_KEY_1
kubectl exec -n vault vault-0 -- vault operator unseal $UNSEAL_KEY_2
kubectl exec -n vault vault-0 -- vault operator unseal $UNSEAL_KEY_3
```

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

**1. VaultAuth ресурс:**
```yaml
apiVersion: secrets.hashicorp.com/v1beta1
kind: VaultAuth
metadata:
  name: static-auth
spec:
  method: kubernetes
  mount: kubernetes
  kubernetes:
    role: webapp-role
    serviceAccount: webapp-sa
```

**2. VaultStaticSecret ресурс:**
```yaml
apiVersion: secrets.hashicorp.com/v1beta1
kind: VaultStaticSecret
metadata:
  name: webapp-kv-secret
spec:
  vaultAuthRef: static-auth
  mount: secret
  path: webapp/config
  destination:
    name: webapp-k8s-secret
    create: true
```

### Шаг 5: Реализация через Secrets Store CSI Driver

**1. SecretProviderClass:**
```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: vault-webapp-provider
spec:
  provider: vault
  parameters:
    roleName: "webapp-role"
    objects: |
      - objectName: "dbpassword"
        secretPath: "secret/data/webapp/config"
        secretKey: "password"
```

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

## Дополнительная информация

### Устранение неисправностей (Troubleshooting)

| Проблема | Причина и решение |
| :--- | :--- |
| **Pending Pod** | Ошибка CSI драйвера. Проверьте `kubectl describe pod` и наличие драйвера на узле. |
| **Permission Denied (Vault)** | Несоответствие `serviceAccount` или `namespace` в роли Vault. Проверьте настройки `auth/kubernetes/role`. |
| **TokenReview Failed** | Ошибка в `auth/kubernetes/config`. Проверьте корректность `kubernetes_host` и `ca_cert`. |
| **VSO не обновляет секрет** | Проверьте логи оператора: `kubectl logs -l app.kubernetes.io/name=vault-secrets-operator`. |

### См. также
*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура SLM.
*   **[Безопасность Kubernetes Secrets](../../Kubernetes/Base/secrets/security.md)** — сравнение методов защиты.
*   **[Vault Agent Sidecar](./vault_agent/sidecar_pattern.md)** — детали работы агента.
*   **[Secrets Store CSI Driver Documentation](https://secrets-store-csi-driver.sigs.k8s.io/)**
