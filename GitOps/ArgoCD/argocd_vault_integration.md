# Интеграция Argo CD и HashiCorp Vault: Argo CD Vault Plugin

> **Актуальность (2026):** Argo CD Vault Plugin (AVP) поддерживается для версий Argo CD v2.x и v3.x. Однако для новых проектов в 2026 году стандартом является **External Secrets Operator (ESO)** из-за архитектурных ограничений AVP (хранение секретов в кэше Redis). Подробнее см. раздел [Безопасность и альтернативы](#безопасность-и-современные-альтернативы).

## Определения

**Argo CD Vault Plugin (AVP)** — плагин управления конфигурациями (Config Management Plugin), предназначенный для динамической подстановки секретных данных из внешних хранилищ (Vault, AWS Secrets Manager, GCP Secret Manager) в манифесты Kubernetes непосредственно в момент их рендеринга на стороне Argo CD.

**HashiCorp Vault** — централизованная система управления секретами, обеспечивающая их безопасное хранение, аудит доступа и динамическую генерацию учетных данных.

- **CMP v2 (Config Management Plugin)** — механизм расширения Argo CD, представленный в версии 2.4, который использует sidecar-контейнеры для изоляции и запуска плагинов генерации манифестов.
- **App-of-Apps** — паттерн проектирования в Argo CD, при котором одно «корневое» приложение управляет жизненным циклом множества дочерних приложений (включая специализированные «приложения с секретами»).


## Базовые концепции

### Проблема хранения секретов в GitOps

В классическом GitOps манифесты хранятся в Git. Поскольку стандартные секреты Kubernetes используют только кодирование Base64 (не шифрование), их хранение в публичных или даже приватных репозиториях без дополнительной защиты является критическим нарушением безопасности.

**Argo CD Vault Plugin** решает эту задачу, позволяя хранить в Git только шаблоны (плейсхолдеры). Реальные значения подставляются только в оперативной памяти компонента `argocd-repo-server` перед отправкой манифестов в API Kubernetes.

### Архитектура и механизм работы

Плагин функционирует как sidecar-контейнер в поде `argocd-repo-server`:

1. **Загрузка:** Argo CD получает манифесты из Git-репозитория.
2. **Обнаружение (Discovery):** CMP-сервер сканирует файлы по заданным правилам (например, наличие специфической аннотации `avp.kubernetes.io/path`).
3. **Запрос:** При обнаружении тегов подстановки (например, `<password>`) плагин аутентифицируется в Vault (обычно через Kubernetes Auth Method).
4. **Рендеринг:** Плагин запрашивает секреты, заменяет теги на реальные значения и возвращает готовый YAML.
5. **Применение:** Argo CD применяет итоговые манифесты. Секреты попадают в кластер, минуя Git.

## Практические сценарии

### Сценарий 1: Подготовка HashiCorp Vault

Прежде чем Argo CD сможет запрашивать секреты, необходимо настроить Vault.

**1. Активация KV-хранилища:**
```bash
# Включение хранилища Key-Value версии 2
vault secrets enable -path=secret kv-v2

# Создание тестового секрета
vault kv put secret/data/myapp/config user="admin" password="super-secret-password"
```

**2. Создание политики доступа:**
```hcl
# myapp-policy.hcl
path "secret/data/myapp/*" {
  capabilities = ["read"]
}
```
Примените политику: `vault policy write myapp-policy myapp-policy.hcl`

**3. Настройка аутентификации Kubernetes:**
```bash
# Включение метода аутентификации
vault auth enable kubernetes

# Настройка связи с API Kubernetes
vault write auth/kubernetes/config \
    issuer="https://kubernetes.default.svc.cluster.local" \
    token_reviewer_jwt="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)" \
    kubernetes_host="https://$KUBERNETES_PORT_443_TCP_ADDR:443" \
    kubernetes_ca_cert=@/var/run/secrets/kubernetes.io/serviceaccount/ca.crt

> **Важный нюанс:** Параметр `issuer` стал обязательным начиная с Vault 1.9.0 для работы с Kubernetes 1.20+. Без него аутентификация может возвращать ошибку `claim "iss" is invalid`.

# Создание роли для Argo CD
vault write auth/kubernetes/role/argocd-role \
    bound_service_account_names=argocd-repo-server \
    bound_service_account_namespaces=argocd \
    policies=myapp-policy \
    ttl=24h
```

### Сценарий 2: Конфигурация Argo CD (CMP v2)

В современных версиях Argo CD (v2.x, v3.x) плагин настраивается через sidecar.

**1. Создание ConfigMap с описанием плагина:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: avp-cmp-config
  namespace: argocd
data:
  plugin.yaml: |
    apiVersion: argoproj.io/v1alpha1
    kind: ConfigManagementPlugin
    metadata:
      name: argocd-vault-plugin
    spec:
      discover:
        fileName: ".*\\.yaml$"
        annotation: "avp.kubernetes.io/path"
      generate:
        command: ["argocd-vault-plugin"]
        args: ["generate", "-s", "avp-config"]
```

**2. Обновление Deployment `argocd-repo-server`:**
Необходимо добавить sidecar-контейнер и init-контейнер для скачивания бинарного файла плагина (если не используется кастомный образ).

```yaml
spec:
  template:
    spec:
      containers:
      - name: avp
        command: [/var/run/argocd/argocd-cmp-server]
        image: argoproj/argocd:v2.10.0 # Используйте версию, соответствующую вашему Argo CD
        securityContext:
          runAsNonRoot: true
          runAsUser: 999
        volumeMounts:
        - name: var-run-argocd
          mountPath: /var/run/argocd
        - name: plugins
          mountPath: /home/argocd/cmp-server/plugins
        - name: custom-tools
          mountPath: /usr/local/bin/argocd-vault-plugin
          subPath: argocd-vault-plugin
      
      initContainers:
      - name: download-tools
        image: alpine:latest
        command: [sh, -c]
        args:
          - wget -O /custom-tools/argocd-vault-plugin https://github.com/argoproj-labs/argocd-vault-plugin/releases/download/v1.18.1/argocd-vault-plugin_linux_amd64 && chmod +x /custom-tools/argocd-vault-plugin
        volumeMounts:
        - name: custom-tools
          mountPath: /custom-tools
```

### Сценарий 3: Использование плагина в манифестах

**1. Обычный YAML (через аннотации):**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: my-app-secret
  annotations:
    avp.kubernetes.io/path: "secret/data/myapp/config"
type: Opaque
stringData:
  username: <user>
  password: <password>
```

**2. Helm Charts (в values.yaml):**
В файле `values.yaml` можно использовать полный путь:
```yaml
db:
  pass: <path:secret/data/myapp/config#password>
```

**3. Синтаксис тегов:**
- `<key>` — подстановка значения по ключу из пути, указанного в аннотации.
- `<path#key>` — явное указание пути и ключа в одном теге.

### Сценарий 4: Настройка объекта Application

Для активации плагина необходимо указать его имя в спецификации приложения и передать переменные окружения для подключения к Vault.

```yaml
spec:
  source:
    path: manifests
    plugin:
      name: argocd-vault-plugin
      env:
        - name: AVP_TYPE
          value: vault
        - name: AVP_AUTH_TYPE
          value: kubernetes
        - name: AVP_K8S_ROLE
          value: argocd-role
        - name: VAULT_ADDR
          value: http://vault.vault.svc:8200
```

### Сценарий 5: Автоматическое обновление подов (Rolling Update)

Argo CD не видит изменений *внутри* Vault. Если пароль изменился в Vault, но манифест в Git остался прежним, Argo CD не запустит синхронизацию. 
Решение — использование хеширования в аннотациях Deployment (в Helm-чартах).

```yaml
kind: Deployment
spec:
  template:
    metadata:
      annotations:
        # Хеш содержимого секрета. При изменении данных в Vault плагин подставит 
        # новые значения, хеш изменится, что вызовет перезапуск подов.
        checksum/vault-secrets: {{ include (print $.Template.BasePath "/secret.yaml") . | sha256sum }}
```

## Технический справочник

### Переменные окружения AVP

| Переменная | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `AVP_TYPE` | Тип бэкенда (vault, aws, gcp, azurekeyvault) | `vault` |
| `AVP_AUTH_TYPE` | Метод аутентификации (token, kubernetes, approle, iam) | `token` |
| `VAULT_ADDR` | Адрес API Vault | `http://localhost:8200` |
| `AVP_K8S_ROLE` | Роль для Kubernetes Auth | — |
| `VAULT_NAMESPACE` | Пространство имен Vault (для Vault Enterprise) | — |
| `AVP_PATH_VERSION` | Версия KV-хранилища | `latest` |

### Способы установки бинарного файла

1. **Init-container:** Оптимально для быстрого старта (см. Сценарий 2).
2. **Custom Image:** Сборка собственного образа `argocd-repo-server`. Рекомендуется для Production.
3. **Volume Mount:** Монтирование бинарного файла из внешнего тома (например, NFS или ConfigMap с бинарными данными).

## Безопасность и современные альтернативы (2026)

### Критические риски AVP в 2026 году:

1. **Кэширование в Redis:** Argo CD кэширует результат рендеринга (готовый YAML с паролями) в своем Redis. Это означает, что **секреты хранятся в открытом виде в кэше**. Требуется обязательное шифрование Redis и защита NetworkPolicy.
2. **Source Hydrator (v3.x):** В Argo CD v3 представлена функция гидрации (hydration), которая сохраняет отрендеренные манифесты в Git для аудита. **Использование AVP с гидрацией приведет к коммиту секретов в Git.**

### Рекомендация: External Secrets Operator (ESO)

В 2026 году ESO является предпочтительным решением для связки Argo CD + Vault.
- **Безопасность:** Секреты никогда не попадают в Argo CD. ESO работает в целевом кластере и синхронизирует данные из Vault напрямую в Kubernetes Secret.
- **Нативность:** Вы используете CRD `ExternalSecret`, который безопасно хранить в Git.
- **Автоматизация:** ESO сам отслеживает изменения в Vault и обновляет секреты без необходимости перезапуска синхронизации Argo CD.

## Диагностика (Troubleshooting)

**1. Логи sidecar-контейнера:**
```bash
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server -c avp
```

**2. Проверка доступности Vault:**
Убедитесь, что `argocd-repo-server` имеет сетевой доступ к `VAULT_ADDR`.

**3. Ошибки Permission Denied:**
Проверьте, что ServiceAccount `argocd-repo-server` (должен иметь `create: true` в Helm-values) привязан к правильной роли в Vault и политики разрешают `read` по указанному пути.

**4. Секреты не обновляются:**
Если вы изменили значение в Vault, но Argo CD не видит изменений (так как манифест в Git не менялся), выполните принудительную синхронизацию:
```bash
argocd app sync <app-name> --force
```
Или используйте метод с хешированием аннотаций (см. Сценарий 5).

## См. также

- [Управление секретами в GitOps](../secrets_encryption.md)
- [Обзор Argo CD: Безопасность](./argocd_overview.md)
- [Официальный репозиторий AVP](https://github.com/argoproj-labs/argocd-vault-plugin)
- [Документация External Secrets Operator](https://external-secrets.io/)
