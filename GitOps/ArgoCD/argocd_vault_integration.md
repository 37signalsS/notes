# ArgoCD и HashiCorp Vault: Интеграция через ArgoCD Vault Plugin

> **Актуальная версия плагина:** v1.18.x (2025). Совместимость: ArgoCD v1.8.x, v2.x. Для ArgoCD v3 требуется тестирование.

## Определения

**ArgoCD Vault Plugin (AVP)** — плагин для ArgoCD, который позволяет подставлять секретные данные из HashiCorp Vault (и других менеджеров секретов) в Kubernetes-манифесты непосредственно в момент синхронизации.

## Базовые концепции

### Проблема хранения секретов в Git

Секреты Kubernetes по умолчанию хранятся в base64-кодировке, что не обеспечивает криптографической защиты. Хранение незашифрованных секретов в Git является критическим анти-паттерном безопасности.

**ArgoCD Vault Plugin** решает эту проблему за счет интеграции с HashiCorp Vault. Плагин динамически подставляет секреты из Vault в манифесты во время синхронизации, исключая их попадание в Git-репозиторий.

### Архитектура AVP

Плагин функционирует как sidecar-контейнер в поде `argocd-repo-server`:

1. ArgoCD получает исходные манифесты из Git.
2. AVP сканирует манифесты на наличие специфических тегов или аннотаций.
3. При обнаружении тегов AVP аутентифицируется и запрашивает соответствующие значения из Vault.
4. AVP подставляет полученные значения вместо тегов в манифесты.
5. ArgoCD применяет итоговые манифесты в кластер Kubernetes.

### Типы поддерживаемых манифестов

- **Plain YAML:** Стандартные манифесты с использованием аннотаций.
- **Helm Charts:** Чарты с использованием специального синтаксиса в файлах конфигурации (`values`).
- **Kustomize:** Интеграция с манифестами Kustomize.

## Практические сценарии

### Сценарий 1: Подготовка Vault

**1. Активация KV store:**

```bash
# Включение KV v2
vault secrets enable -path=secret kv-v2

# Создание секрета
vault kv put secret/test user="myuser" password="mypassword"
```

**2. Настройка политики доступа:**

```hcl
# test-policy.hcl
path "secret/data/test" {
  capabilities = ["read"]
}
```

**3. Настройка аутентификации Kubernetes:**

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

### Сценарий 2: Конфигурация ArgoCD с плагином AVP

**Пример конфигурации через Helm (values.yaml):**

```yaml
repoServer:
  replicas: 1
  
  # Init-container для скачивания бинарного файла плагина
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
  
  # Sidecar-контейнер для запуска плагина
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
  
  # Включение Config Management Plugins (CMP)
  config:
    cmp:
      create: true

# Определение плагина
plugins:
- name: avp
  generate:
    command: [argocd-vault-plugin]
    args: ["generate", "-s", "avp-config"]
```

### Сценарий 3: Использование AVP в манифестах

**Plain YAML (через аннотации):**

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

**Helm Charts (в values.yaml):**

```yaml
secret:
  username: <username>
  password: <password>
```

**Синтаксис тегов подстановки:**

- `<path#key>` — полный путь (например, `secret/data/test#username`).
- `<key>` — только ключ (путь извлекается из аннотации манифеста).

### Сценарий 4: Настройка Application в ArgoCD

Для активации плагина на уровне конкретного приложения необходимо передать параметры окружения:

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
        value: my-namespace  # Используется для Vault Enterprise
  destination:
    server: https://kubernetes.default.svc
    namespace: default
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

### Сценарий 5: Автоматическое обновление подов (Rollout) при изменении секрета в Vault

ArgoCD не отслеживает изменения данных *внутри* Vault автоматически. Если вы изменили пароль в Vault, ArgoCD не увидит изменений в Git и не перезапустит поды. Для решения этой проблемы в Helm-чартах используется техника хеширования секрета в аннотациях пода.

**Реализация в Helm-чарте (`templates/deployment.yaml`):**

```yaml
kind: Deployment
spec:
  template:
    metadata:
      annotations:
        # Хеширование содержимого секрета. При изменении секрета в Vault
        # плагин ArgoCD Vault Plugin подставит новые данные, хеш изменится,
        # что инициирует Rolling Update пода.
        checksum/vault-secrets: {{ include (print $.Template.BasePath "/secret.yaml") . | sha256sum }}
```

**Как это работает:**
1. При синхронизации `argocd-repo-server` выполняет `helm template`.
2. Плагин подставляет реальные значения из Vault.
3. Функция `sha256sum` рассчитывает хеш от итогового манифеста секрета.
4. Если хеш в аннотации `checksum/vault-secrets` изменился по сравнению с текущим в кластере, Kubernetes инициирует перезапуск подов (Rolling Update).

> **Примечание:** Этот метод работает, если вы используете ArgoCD Vault Plugin для генерации объекта `Secret` внутри кластера. Если приложение ходит в Vault напрямую (через Sidecar или SDK), используйте **[Reloader](../../Kubernetes/ToolsUtilities/reloader/reloader_overview.md)**.

## Дополнительная информация

### Конфигурация обнаружения (Discovery)

Плагин использует механизм `discovery` для определения файлов, требующих обработки:

```yaml
discover:
  fileName: ".*\\.yaml$"
  annotation: "avp.kubernetes.io/path"
generate:
  command: ["argocd-vault-plugin", "generate", "-s", "avp-config"]
```

### Варианты установки бинарного файла AVP

| Метод | Описание | Применение |
| :--- | :--- | :--- |
| **Init-container** | Скачивание бинарного файла при старте пода | Быстрое развёртывание, тестирование |
| **Custom image** | Создание собственного образа с предустановленным плагином | Production, строгий контроль версий |
| **Helm hook** | Установка через `post-install` хуки Helm | Автоматизация развертывания |

### Переменные окружения AVP

| Переменная | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `AVP_TYPE` | Тип бэкенда секретов (vault, aws, gcp) | `vault` |
| `AVP_AUTH_TYPE` | Метод аутентификации | `kubernetes` |
| `VAULT_ADDR` | Сетевой адрес Vault | `http://localhost:8200` |
| `AVP_K8S_ROLE` | Имя Kubernetes-роли для аутентификации в Vault | — |
| `VAULT_NAMESPACE` | Пространство имен Vault (для Vault Enterprise) | — |
| `AVP_PATH_VERSION` | Версия хранилища KV-секретов | `latest` |

### Ограничения и особенности

- Плагин функционирует исключительно в контексте компонента `repo-server`.
- Для различных типов конфигурации (Helm, Kustomize, Plain YAML) требуется создание отдельных sidecar-контейнеров.
- Обязательно наличие сетевого доступа от подов `repo-server` к API Vault.
- Использование с Helm требует применения специфического синтаксиса подстановки в файлах `values`.

### Диагностика (Troubleshooting)

**Проверка логов плагина:**

```bash
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server -c avp
```

**Распространенные ошибки:**

- `permission denied` — ошибка доступа; проверьте политики Vault и привязку ролей.
- `connection refused` — сетевая ошибка; проверьте доступность Vault по указанному `VAULT_ADDR`.
- `secret not found` — секрет не найден; проверьте правильность пути в Vault и версию секрета.

### См. также

- [ArgoCD Overview: Управление секретами](./argocd_overview.md#управление-секретами)
- [GitOps: Управление секретами](../secrets_encryption.md)
- [Официальная документация ArgoCD Vault Plugin](https://argocd-vault-plugin.readthedocs.io/)
- [GitHub репозиторий AVP](https://github.com/argoproj-labs/argocd-vault-plugin)
