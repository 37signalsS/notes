# Интеграция Argo CD и HashiCorp Vault: Argo CD Vault Plugin

> **Актуальность (2026):** Argo CD Vault Plugin (AVP) по-прежнему используется для проектов с глубокой кастомизацией манифестов на лету. Однако отраслевым стандартом 2026 года для Kubernetes-native сред являются **External Secrets Operator (ESO)** и официальный **Vault Secrets Operator (VSO)**. Основная причина — архитектурные риски AVP, связанные с кэшированием секретов в Redis. Подробнее см. раздел [Безопасность и современные альтернативы](#безопасность-и-современные-альтернативы-2026).

## Определения

**Argo CD Vault Plugin (AVP)** — плагин управления конфигурациями (Config Management Plugin), предназначенный для динамической подстановки секретных данных из внешних хранилищ (Vault, AWS Secrets Manager, GCP Secret Manager, Azure Key Vault) в манифесты Kubernetes непосредственно в момент их рендеринга на стороне Argo CD.

**HashiCorp Vault** — централизованная система управления секретами, обеспечивающая их безопасное хранение, аудит доступа и динамическую генерацию учетных данных.

- **CMP v2 (Config Management Plugin)** — современный механизм расширения Argo CD (начиная с v2.4), использующий sidecar-контейнеры в поде `argocd-repo-server` для выполнения логики генерации манифестов в изолированном окружении.
- **App-of-Apps** — паттерн проектирования в Argo CD, при котором одно «корневое» приложение управляет жизненным циклом множества дочерних приложений (включая специализированные «приложения с секретами»).
- **Secret Zero (Проблема первого секрета)** — проблема безопасной доставки первичных учетных данных (токена или ключа), необходимых для первоначальной аутентификации во внешнем хранилище.

## Базовые концепции

### Проблема хранения секретов в GitOps

В классическом GitOps манифесты хранятся в Git. Поскольку стандартные секреты Kubernetes используют только кодирование Base64, их хранение в репозиториях без шифрования (например, через SOPS или Sealed Secrets) является критическим нарушением безопасности.

**Argo CD Vault Plugin** позволяет хранить в Git только шаблоны (плейсхолдеры). Реальные значения подставляются только в оперативной памяти компонента `argocd-repo-server` перед отправкой манифестов в API Kubernetes.

### Архитектура и механизм работы (CMP v2)

Плагин функционирует как sidecar-контейнер в поде `argocd-repo-server`:

1.  **Загрузка (Fetch):** Argo CD получает манифесты из Git-репозитория.
2.  **Обнаружение (Discovery):** CMP-сервер сканирует файлы по заданным правилам (например, наличие специфической аннотации `avp.kubernetes.io/path` или совпадение имени файла).
3.  **Аутентификация:** Плагин аутентифицируется в Vault (обычно через Kubernetes Auth Method).
4.  **Рендеринг (Generate):** Плагин запрашивает секреты, заменяет теги на реальные значения и возвращает готовый YAML.
5.  **Применение (Apply):** Argo CD применяет итоговые манифесты. Секреты попадают в кластер, минуя Git.

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

**2. Создание политики доступа (myapp-policy.hcl):**
```hcl
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

В современных версиях Argo CD плагин настраивается через sidecar.

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
Необходимо добавить sidecar-контейнер и init-контейнер для скачивания бинарного файла плагина.

```yaml
spec:
  template:
    spec:
      containers:
      - name: avp
        command: [/var/run/argocd/argocd-cmp-server]
        image: argoproj/argocd:v2.10.0 # Версия должна соответствовать Argo CD
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
      
      volumes:
      - name: custom-tools
        emptyDir: {}
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

Для активации плагина необходимо указать его имя и передать переменные окружения.

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

Argo CD не видит изменений *внутри* Vault. Если пароль изменился в Vault, но манифест в Git не менялся, Argo CD не запустит синхронизацию.
Решение — использование хеширования в аннотациях Deployment.

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

## Сравнение методов интеграции (2026)

| Критерий | Argo CD Vault Plugin (AVP) | External Secrets Operator (ESO) | Vault Secrets Operator (VSO) |
| :--- | :--- | :--- | :--- |
| **Принцип работы** | Подстановка при рендеринге | Синхронизация в K8s Secret | Нативный контроллер Vault |
| **Где хранятся секреты** | В памяти repo-server + Redis | В etcd (как Secret) | В etcd / Памяти подов |
| **Авто-обновление** | Требует ручного Sync / Хеширования | Автоматическое (polling) | Нативное (Event-driven) |
| **Сложность** | Средняя (CMP v2 sidecar) | Средняя (CRD) | Высокая (Official Operator) |
| **Рекомендация** | Legacy / Сложные шаблоны | **Standard (Production)** | **Enterprise / Vault Native** |

## Безопасность и современные альтернативы 2026

### Основные риски использования AVP

1.  **Кэширование в Redis:** Argo CD кэширует результат рендеринга (готовый YAML с паролями) в своем Redis. Это означает, что **секреты хранятся в открытом виде в кэше**.
    *   *Решение:* Обязательное шифрование Redis и защита NetworkPolicy.
2.  **Source Hydrator (v3.x):** В Argo CD v3 функция гидрации (hydration), которая сохраняет отрендеренные манифесты в Git для аудита, несовместима с AVP, так как секреты попадут в коммит.

### Рекомендация: External Secrets Operator (ESO) и VSO

В 2026 году ESO и VSO являются предпочтительными решениями.
- **Безопасность:** Секреты никогда не попадают в Argo CD.
- **Нативность:** Использование CRD (`ExternalSecret` или `VaultStaticSecret`), которые безопасно хранить в Git.
- **Автоматизация:** Операторы сами отслеживают изменения в Vault и обновляют секреты без необходимости ручной синхронизации в Argo CD.

## Технический справочник

### Ключевые переменные окружения AVP

| Переменная | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `AVP_TYPE` | Тип бэкенда (vault, aws, gcp, azurekeyvault) | `vault` |
| `AVP_AUTH_TYPE` | Метод аутентификации (token, kubernetes, approle, iam) | `token` |
| `VAULT_ADDR` | Адрес API Vault | `http://localhost:8200` |
| `AVP_K8S_ROLE` | Роль для Kubernetes Auth | — |
| `VAULT_NAMESPACE` | Пространство имен (для Vault Enterprise) | — |
| `AVP_PATH_VERSION` | Версия KV-хранилища | `latest` |

### Способы установки бинарного файла

1.  **Init-container:** Оптимально для быстрого старта (см. Сценарий 2).
2.  **Custom Image:** Сборка собственного образа `argocd-repo-server`. Рекомендуется для Production.
3.  **Volume Mount:** Монтирование из внешнего тома (NFS, ConfigMap с бинарными данными).

## Диагностика и типичные ошибки

**1. Логи sidecar-контейнера:**
```bash
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server -c avp
```

**2. Ошибки Permission Denied (403):**
- Проверьте, что ServiceAccount `argocd-repo-server` привязан к правильной роли в Vault.
- Убедитесь, что политики разрешают `read` по полному пути (с учетом `data/` для KV v2).

**3. Ошибка "Vault is sealed":**
Плагин вернет ошибку 500. Проверьте состояние: `vault status`.

**4. Секреты не обновляются:**
Выполните принудительную синхронизацию: `argocd app sync <app-name> --force` или используйте метод с хешированием аннотаций (Сценарий 5).

## См. также

- [Управление секретами в GitOps](../secrets_encryption.md)
- [Обзор Argo CD: Безопасность](./argocd_overview.md)
- [Интеграция Vault с Kubernetes](../../Vault/guides/vault_kubernetes_integration.md)
- [Внешние системы управления секретами](../../Kubernetes/Base/secrets/external_managers.md)
- [Официальный репозиторий AVP](https://github.com/argoproj-labs/argocd-vault-plugin)
