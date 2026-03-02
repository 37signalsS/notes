# Интеграция HashiCorp Vault с Kubernetes через Secrets Store CSI Driver

## 1. Обзор

Стандартные секреты Kubernetes (`Secret`) обеспечивают лишь базовый уровень безопасности, храня данные в `etcd` в закодированном (Base64), но не зашифрованном виде. Для production-сред с высокими требованиями к безопасности рекомендуется использовать внешние, более надежные хранилища, такие как **[HashiCorp Vault](../overview.md)**.

Эта заметка описывает один из самых надежных и гибких способов интеграции — использование **Secrets Store CSI Driver**.

## 2. Стратегии интеграции Vault и Kubernetes

Существует два основных подхода для доставки секретов из Vault в поды Kubernetes:

| Подход | Описание | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **Vault Agent (Sidecar)** | В под добавляется дополнительный контейнер (`sidecar`), который аутентифицируется в Vault, извлекает секреты и записывает их в общий том (`emptyDir`) или передает через переменные окружения. Подробнее см. в [**Vault Agent и Шаблоны**](./vault_agent_and_templates.md). | - Не требует компонентов на уровне всего кластера.<br>- Хорошо подходит для динамической ротации секретов с перезагрузкой приложения по сигналу (`SIGHUP`). | - Требует модификации каждого `Deployment`.<br>- Неудобен для приложений, которые не умеют читать конфигурацию из файлов или переменных окружения после старта (например, для Nginx, где нужно сгенерировать `nginx.conf` до запуска). |
| **Secrets Store CSI Driver** | Драйвер, работающий на уровне кластера, монтирует секреты из Vault непосредственно в под как виртуальный том (`volume`). Приложение видит секреты как обычные файлы. | - **Нативный для Kubernetes:** Использует стандартный интерфейс [CSI (Container Storage Interface)](../../Kubernetes/Storage/CSI/csi_overview.md).<br>- **Гибкость:** Идеально подходит для использования с `initContainer` для генерации конфигурационных файлов перед стартом основного приложения.<br>- **Универсальность:** Поддерживает множество провайдеров (Vault, Azure Key Vault, GCP Secret Manager и др.). | - Требует установки и настройки компонентов на уровне всего кластера (CSI Driver и провайдер для Vault). |

В этом руководстве мы рассмотрим второй подход как более универсальный.

## 3. Практический сценарий: Интеграция через CSI-драйвер

Сценарий демонстрирует запуск пода с `nginx` (OpenResty), конфигурационный файл которого (`index.html`) будет сгенерирован `initContainer`-ом на основе шаблона и секретов, полученных из Vault.

### Шаг 1: Установка компонентов

**1. Установка Vault через Helm**

Рекомендуется использовать официальный Helm-чарт. В данном примере Vault настраивается для работы в HA-режиме с PostgreSQL в качестве бэкенда (вместо Consul), так как драйвер S3 не поддерживает HA-режим.

Пример `values.yaml` для установки Vault:
```yaml
injector:
  enabled: false # Отключаем sidecar injector, так как используем CSI

server:
  ha:
    enabled: true
    replicas: 2
    
  # Для использования PostgreSQL в качестве бэкенда,
  # вместо встроенного Consul
  dataStorage:
    enabled: false
  
  extraVolumes:
    - type: 'secret'
      name: 'vault-postgresql-secret' # Секрет с данными для подключения к PG

  standalone:
    enabled: false

  # Конфигурация Vault (vault.hcl)
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
# Включаем поддержку CSI
csi:
  enabled: true
```

**2. Установка Secrets Store CSI Driver**

Также устанавливается через Helm.
```bash
helm repo add secrets-store-csi-driver https://kubernetes-sigs.github.io/secrets-store-csi-driver/charts
helm install csi-secrets-store secrets-store-csi-driver/secrets-store-csi-driver --namespace kube-system
```

### Шаг 2: Инициализация и "распечатывание" Vault

После установки поды Vault будут запущены, но "запечатаны" (`Sealed`).
> **Важно:** Процедуру `unseal` необходимо выполнять для каждого пода Vault после его перезапуска. В production это автоматизируется.

1.  **Инициализация (выполняется один раз):**
    ```bash
    kubectl exec -n vault vault-0 -- vault operator init -key-shares=1 -key-threshold=1 -format=json > cluster-keys.json
    ```
    Сохраните `cluster-keys.json` в надежном месте. В нем содержатся ключ для распечатывания (`unseal_keys_b64`) и корневой токен (`root_token`).

2.  **Распечатывание:**
    ```bash
    # Получаем ключ из файла
    UNSEAL_KEY=$(jq -r ".unseal_keys_b64[0]" cluster-keys.json)

    # Распечатываем каждую реплику
    kubectl exec -n vault vault-0 -- vault operator unseal $UNSEAL_KEY
    kubectl exec -n vault vault-1 -- vault operator unseal $UNSEAL_KEY
    ```

### Шаг 3: Настройка Vault для аутентификации Kubernetes

1.  **Логин в Vault:**
    ```bash
    ROOT_TOKEN=$(jq -r ".root_token" cluster-keys.json)
    kubectl exec -n vault -it vault-0 -- /bin/sh
    # Внутри пода:
    vault login $ROOT_TOKEN
    ```

2.  **Включение движка секретов и аутентификации Kubernetes:**
    ```sh
    # Включаем KV-v2 движок
    vault secrets enable -path=secret kv-v2

    # Включаем метод аутентификации Kubernetes
    vault auth enable kubernetes
    ```

3.  **Конфигурация аутентификации:**
    Указываем Vault, как найти и проверить API-сервер Kubernetes.
    ```sh
    vault write auth/kubernetes/config 
       token_reviewer_jwt="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)" 
       kubernetes_host="https://kubernetes.default.svc" 
       kubernetes_ca_cert=@/var/run/secrets/kubernetes.io/serviceaccount/ca.crt
    ```

4.  **Создание секрета, политики и роли:**
    ```sh
    # 1. Помещаем секрет в Vault
    vault kv put secret/webapp/config username="db-user" password="Password123!"

    # 2. Создаем политику, разрешающую чтение этого секрета
    vault policy write webapp-policy - <<EOF
    path "secret/data/webapp/config" {
      capabilities = ["read"]
    }
    EOF

    # 3. Создаем роль, связывающую ServiceAccount из Kubernetes с политикой Vault
    vault write auth/kubernetes/role/webapp-role 
        bound_service_account_names=webapp-sa 
        bound_service_account_namespaces=default 
        policies=webapp-policy 
        ttl=24h
    ```

### Шаг 4: Развертывание приложения

**1. `SecretProviderClass`**

Это CRD, который говорит CSI-драйверу, как и откуда получать секреты.
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

**2. `Deployment`**

-   Создаем `ServiceAccount` `webapp-sa`.
-   В `Deployment` указываем `serviceAccountName: webapp-sa`.
-   Монтируем CSI-том, ссылающийся на `SecretProviderClass`.
-   `initContainer` читает секреты из тома и генерирует `index.html`.
-   Основной контейнер использует сгенерированный файл.

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
              #!/bin/sh
              TEMPLATE_PATH=/template/index.html
              CONFIG_PATH=/config/index.html
              
              # Ждем, пока файлы секретов не появятся
              while [ ! -f /mnt/secrets/username ] || [ ! -f /mnt/secrets/password ]; do
                echo "Waiting for secrets..."
                sleep 2
              done

              # Подставляем значения
              sed "s|\${USERNAME}|$(cat /mnt/secrets/username)|g; s|\${PASSWORD}|$(cat /mnt/secrets/password)|g" 
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
              mountPath: /usr/local/openresty/nginx/html # Путь, где nginx ищет index.html
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

После применения всех манифестов `initContainer` получит секреты, создаст `index.html`, и `nginx` запустится с уже готовой конфигурацией, не имея прямого доступа к Vault.

## 4. Ссылки по теме

* **[Обзор HashiCorp Vault](../overview.md):** Общее описание технологии и ключевых компонентов.
* **[Основные концепции Vault](../concepts.md):** Архитектура, Seal/Unseal, бэкенды, аутентификация.
* **[Обзор Container Storage Interface (CSI)](../../Kubernetes/Storage/CSI/csi_overview.md):** Принцип работы CSI в Kubernetes.
* **[Vault Agent и Шаблоны](./vault_agent_and_templates.md):** Альтернативный подход с использованием sidecar-контейнера.
* **[Подход Zero Trust](../zero_trust.md):** Как интеграция с Kubernetes реализует принципы нулевого доверия.
* **[Официальная документация: Vault + Kubernetes](https://developer.hashicorp.com/vault/docs/platform/k8s):** Полное руководство от HashiCorp.
* **[Secrets Store CSI Driver](https://secrets-store-csi-driver.sigs.k8s.io/):** Документация проекта.

