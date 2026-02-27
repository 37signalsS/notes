# ArgoCD + HashiCorp Vault: Интеграция через ArgoCD Vault Plugin

## Определения

**ArgoCD Vault Plugin** — это плагин для ArgoCD, который позволяет подставлять секретные данные из HashiCorp Vault в Kubernetes-манифесты непосредственно в момент синхронизации приложения.

## Базовые концепции

### Проблема хранения секретов в Git

Секреты в Kubernetes (Secret) хранятся в закодированном виде (base64), но это не является шифрованием — любой может декодировать их. Хранение секретов в Git-репозитории считается моветоном, так как доступ к Git дает доступ к секретам.

### Архитектура решения

ArgoCD Vault Plugin работает как sidecar-контейнер в repo-server:
1. ArgoCD получает манифесты из Git
2. Plugin обнаруживает специальные теги/аннотации
3. Plugin обращается к Vault для получения секретов
4. Plugin подставляет значения вместо тегов
5. ArgoCD применяет готовые манифесты в кластер

### Типы поддерживаемых манифестов

- **Plain YAML**: Обычные манифесты с аннотациями
- **Helm Charts**: Чарты с использованием специального синтаксиса в values
- **Kustomize**: Использование с Kustomize

## Практические сценарии

### 1. Настройка Vault

Создание KV store, аутентификации и политики:

```bash
# Создание KV v2 storage
vault kv put secret/test user="myuser" password="mypassword"

# Политика доступа (secret/data/test -> test/data/user)
path "secret/data/test" {
  capabilities = ["read"]
}

# Настройка Kubernetes аутентификации в Vault
vault auth enable kubernetes

# Создание роли для ArgoCD
vault write auth/kubernetes/role/argocd \
    bound_service_account_names=argocd-repo-server \
    bound_service_account_namespaces=argocd \
    policies=test-policy \
    ttl=1h
```

### 2. Конфигурация ArgoCD с плагином

Добавление в Helm values ArgoCD:

```yaml
repoServer:
  replicas: 1
  
  initContainers:
    - name: download-tools
      image: alpine:latest
      command: [sh, -c]
      args:
        - wget -O /custom-tools/argocd-vault-plugin https://github.com/argoproj-labs/argocd-vault-plugin/releases/download/v1.4.0/argocd-vault-plugin_linux_amd64
      volumeMounts:
        - name: custom-tools
          mountPath: /custom-tools

  volumes:
    - name: custom-tools
      emptyDir: {}

  extraContainers:
    - name: avp
      command: [/var/run/argocd/argocd-cmp-server]
      image: argoproj/argocd:latest
      securityContext:
        runAsNonRoot: true
        runAsUser: 999
      volumeMounts:
        - name: custom-tools
          mountPath: /custom-tools
        - name: cmp-plugins
          mountPath: /home/argocd-cmp-server/plugins

config:
  cmp:
    create: true
    
plugins:
  - name: avp
    generate:
      command: [argocd-vault-plugin]
      args: ["generate", "-s", "avp-config"]
```

### 3. Использование в манифестах

#### Plain YAML (с аннотациями):

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: my-secret
  annotations:
    avp.kubernetes.io/path: "secret/data/test"
type: Opaque
stringData:
  username: <username>
  password: <password>
```

#### Helm Charts (values.yaml):

```yaml
secret:
  username: <username>
  password: <password>
```

Синтаксис: `<path#key>` или `<key>`, где:
- `path` — путь в Vault (secret/data/test)
- `key` — ключ (username, password)

### 4. Настройка Application в ArgoCD

При создании Application необходимо указать параметры плагина в поле `source.plugin`:

```yaml
spec:
  source:
    plugin:
      name: avp
      env:
        - name: AVP_TYPE
          value: vault
        - name: AVP_AUTH_TYPE
          value: kubernetes
        - name: AVP_K8S_ROLE
          value: argocd
        - name: VAULT_ADDR
          value: http://vault.vault.svc:8200
```

## Дополнительная информация

### Конфигурация discovery в плагине

Plugin использует две секции:
- **Discover**: Определяет файлы для обработки (по имени файла или аннотации)
- **Generate**: Определяет команду для обработки файлов

### Варианты установки бинарника плагина

1. **Init-container**: Скачивание при старте (используется в примере)
2. **Custom image**: Создание своего образа repo-server с предустановленным плагином

### Ограничения

- Плагин работает только с repo-server
- Для каждой конфигурации (Helm, Kustomize, Plain) создается отдельный sidecar-контейнер
- При использовании Helm логика работы через специальный синтаксис в values

### Альтернативы

- Sealed Secrets — шифрование секретов для Git
- SOPS — шифрование файлов целиком
- External Secrets Operator — синхронизация секретов из внешних провайдеров
