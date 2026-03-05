# ArgoCD + HashiCorp Vault: Интеграция через ArgoCD Vault Plugin

> **Версия плагина:** v1.18.1 (июнь 2024). Совместимость с ArgoCD v3 требует тестирования.

## Определения

**ArgoCD Vault Plugin (AVP)** — плагин для ArgoCD, который позволяет подставлять секретные данные из HashiCorp Vault (и других секрет-менеджеров) в Kubernetes-манифесты непосредственно в момент синхронизации.

## Базовые концепции

### Проблема хранения секретов в Git

Секреты Kubernetes хранятся в base64-кодировке, что не является шифрованием. Хранение секретов в Git считается анти-паттерном.

**Решения:**

| Инструмент | Принцип | Когда использовать |
| :--- | :--- | :--- |
| **Sealed Secrets** | Шифрование секретов для Git | Простые сценарии, один кластер |
| **SOPS** | Шифрование файлов целиком | Частые изменения секретов |
| **External Secrets** | Синхронизация из внешних провайдеров | Мульти-облачные окружения |
| **ArgoCD Vault Plugin** | Подстановка из Vault при синхронизации | Интеграция с существующим Vault |

### Архитектура AVP

Плагин работает как sidecar-контейнер в `argocd-repo-server`:

1. ArgoCD получает манифесты из Git
2. AVP обнаруживает специальные теги/аннотации
3. AVP обращается к Vault для получения секретов
4. AVP подставляет значения вместо тегов
5. ArgoCD применяет готовые манифесты в кластер

### Типы поддерживаемых манифестов

- **Plain YAML:** Обычные манифесты с аннотациями
- **Helm Charts:** Чарты с использованием специального синтаксиса в values
- **Kustomize:** Использование с Kustomize

## Практические сценарии

### Сценарий 1: Настройка Vault

**1. Создание KV store:**

```bash
# Включение KV v2
vault secrets enable -path=secret kv-v2

# Создание секрета
vault kv put secret/test user="myuser" password="mypassword"
```

**2. Политика доступа:**

```hcl
# test-policy.hcl
path "secret/data/test" {
  capabilities = ["read"]
}
```

**3. Kubernetes аутентификация:**

```bash
# Включение метода аутентификации
vault auth enable kubernetes

# Настройка Kubernetes auth
vault write auth/kubernetes/config \
    kubernetes_host="https://kubernetes.default.svc:443" \
    kubernetes_ca_cert=@/var/run/secrets/kubernetes.io/serviceaccount/ca.crt

# Создание роли для ArgoCD
vault write auth/kubernetes/role/argocd \
    bound_service_account_names=argocd-repo-server \
    bound_service_account_namespaces=argocd \
    policies=test-policy \
    ttl=1h
```

### Сценарий 2: Конфигурация ArgoCD с плагином

**Установка через Helm:**

```yaml
# values.yaml для argo-cd Helm chart
repoServer:
  replicas: 1
  
  # Init-container для загрузки плагина
  initContainers:
  - name: download-tools
    image: alpine:latest
    command: [sh, -c]
    args:
      - wget -O /custom-tools/argocd-vault-plugin \
        https://github.com/argoproj-labs/argocd-vault-plugin/releases/download/v1.18.1/argocd-vault-plugin_linux_amd64 && \
        chmod +x /custom-tools/argocd-vault-plugin
    volumeMounts:
    - name: custom-tools
      mountPath: /custom-tools
  
  volumes:
  - name: custom-tools
    emptyDir: {}
  - name: cmp-plugins
    emptyDir: {}
  
  # Sidecar для плагина
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
  
  # Конфигурация Config Management Plugins
  config:
    cmp:
      create: true

# Плагин
plugins:
- name: avp
  generate:
    command: [argocd-vault-plugin]
    args: ["generate", "-s", "avp-config"]
```

### Сценарий 3: Использование в манифестах

**Plain YAML (с аннотациями):**

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

**Helm Charts (values.yaml):**

```yaml
secret:
  username: <username>
  password: <password>
```

**Синтаксис тегов:**

- `<path#key>` — полный путь (например, `secret/data/test#username`)
- `<key>` — только ключ (путь берётся из аннотации)

### Сценарий 4: Настройка Application в ArgoCD

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/my-org/my-app.git
    targetRevision: HEAD
    path: manifests
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
      - name: VAULT_NAMESPACE
        value: my-namespace  # Для Vault Enterprise
  destination:
    server: https://kubernetes.default.svc
    namespace: default
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

## Дополнительная информация

### Конфигурация discovery в плагине

Плагин использует две секции для определения файлов для обработки:

```yaml
# Пример конфигурации discovery
discover:
  fileName: ".*\\.yaml$"
  annotation: "avp.kubernetes.io/path"
generate:
  command: ["argocd-vault-plugin", "generate", "-s", "avp-config"]
```

### Варианты установки бинарника

| Способ | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Init-container** | Скачивание при старте пода | Быстрое развёртывание, тестирование |
| **Custom image** | Свой образ с предустановленным плагином | Production, контроль версий |
| **Helm hook** | Установка через post-install hook | Автоматизация установки |

### Переменные окружения AVP

| Переменная | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `AVP_TYPE` | Тип бэкенда (vault, aws, gcp) | vault |
| `AVP_AUTH_TYPE` | Метод аутентификации | kubernetes |
| `VAULT_ADDR` | Адрес Vault | <http://localhost:8200> |
| `AVP_K8S_ROLE` | Kubernetes роль для Vault | - |
| `VAULT_NAMESPACE` | Vault namespace (Enterprise) | - |
| `AVP_PATH_VERSION` | Версия KV secret | latest |

### Ограничения

- Плагин работает только с `repo-server`
- Для каждой конфигурации (Helm, Kustomize, Plain) создаётся отдельный sidecar
- Требуется сетевой доступ из `repo-server` в Vault
- При использовании Helm логика работает через специальный синтаксис в values

### Troubleshooting

**Проверка логов:**

```bash
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server -c avp
```

**Частые проблемы:**

- `permission denied` — проверка политики Vault
- `connection refused` — проверка сетевого доступа к Vault
- `secret not found` — проверка пути и версии секрета

### Ссылки

- **[Официальная документация AVP](https://argocd-vault-plugin.readthedocs.io/)**
- **[GitHub репозиторий](https://github.com/argoproj-labs/argocd-vault-plugin)**
- **[Управление секретами в ArgoCD](./argocd_overview.md#управление-секретами)**
