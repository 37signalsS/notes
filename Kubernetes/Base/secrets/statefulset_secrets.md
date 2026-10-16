# Секреты в StatefulSet

## Определения

**StatefulSet** — контроллер Kubernetes для управления stateful-приложениями (базы данных, очереди сообщений, кластерные системы), обеспечивающий стабильные сетевые имена, стабильное хранилище и упорядоченное развёртывание/масштабирование.

**Секреты в контексте StatefulSet** — конфиденциальные данные (пароли БД, ключи репликации, TLS-сертификаты, credentials подключения), необходимые для инициализации и нормальной работы stateful-компонентов. В отличие от Deployment, где секреты обычно статичны, в StatefulSet часто требуется **динамическая ротация** и **привязка к конкретным индексам** реплик.

## Основные концепции

### Особенности использования секретов в StatefulSet

| Особенность | Описание |
| :--- | :--- |
| **Инициализация БД** | Пароль root/администратора передаётся при первом запуске через ENV; после инициализации переменная игнорируется |
| **Стабильные имена** | Каждая реплика имеет предсказуемое имя (`pod-0`, `pod-1`), что позволяет привязывать разные секреты к разным индексам |
| **VolumeClaimTemplates** | Данные хранятся в PVC, привязанных к конкретным подам; секреты не должны попадать на постоянные диски |
| **Репликация** | Пароль репликации (Master-Slave, Galera, Replication Set) должен быть общим для всех реплик |
| **Реконсиляция** | При восстановлении пода из бэкапа Secret может измениться, но данные на диске остаются старыми |

### Модели секретов для StatefulSet

| Модель | Источник секретов | Автообновление | Сложность |
| :--- | :--- | :--- | :--- |
| **Статический Secret** | Kubernetes Secret (ENV/Volume) | Нет (ручная ротация) | Низкая |
| **Dynamic secrets (Vault DB)** | Vault Database Secrets Engine | Да (автоматический TTL) | Средняя |
| **ESO + Vault** | External Secrets Operator | Да (refreshInterval) | Средняя |
| **CSI Driver** | Secrets Store CSI (tmpfs) | Да (при ротации в KMS) | Высокая |
| **Vault Agent Sidecar** | Vault Agent (рендеринг файлов) | Да (SIGHUP/перезапуск) | Высокая |

## Практические сценарии

### Сценарий 1: Статический Secret для MySQL

Самый простой паттерн: Secret создаётся заранее и передаётся в StatefulSet через ENV.

> Полный пример манифеста MySQL StatefulSet с Secret, пробами и ресурсами см. в [StatefulSet: практическое руководство](../../Base/StatefulSet/statefulset_practical_guide.md) (Сценарий 2). Ниже показаны только ключевые элементы, связанные с секретами.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: mysql-credentials
  namespace: prod
type: Opaque
stringData:
  MYSQL_ROOT_PASSWORD: "super-strong-root-password"
  MYSQL_REPLICATION_PASSWORD: "replication-password"
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: mysql
spec:
  serviceName: "mysql"
  replicas: 3
  template:
    spec:
      containers:
      - name: mysql
        image: mysql:8.0
        env:
        - name: MYSQL_ROOT_PASSWORD
          valueFrom:
            secretKeyRef:
              name: mysql-credentials
              key: MYSQL_ROOT_PASSWORD
        - name: MYSQL_REPLICATION_PASSWORD
          valueFrom:
            secretKeyRef:
              name: mysql-credentials
              key: MYSQL_REPLICATION_PASSWORD
```

**Ограничение:** При смене пароля необходимо пересоздать StatefulSet и данные на диске (или выполнять `ALTER USER` вручную). Переменные `MYSQL_*` используются только при **первичной инициализации** — повторное применение манифеста с новым паролем не обновит работающую БД.

### Сценарий 2: Vault Database Secrets Engine (динамические секреты)

Vault генерирует уникальные пароли для каждой реплики с автоматической ротацией.

**Настройка Vault:**

```bash
# Включить движок БД
vault secrets enable database

# Настроить коннект к MySQL
vault write database/config/mysql-host \
  plugin_name=mysql-database-plugin \
  connection_url="{{username}}:{{password}}@tcp(mysql.prod.svc:3306)/" \
  allowed_roles="mysql-readonly" \
  username="vault-admin" \
  password="admin-password"

# Создать роль с TTL
vault write database/roles/mysql-readonly \
  db_name=mysql-host \
  default_ttl="1h" \
  max_ttl="24h" \
  creation_statements="CREATE USER '{{name}}'@'%' IDENTIFIED BY '{{password}}'; \
    GRANT SELECT ON *.* TO '{{name}}'@'%';"
```

**StatefulSet с Vault Agent:**

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: mysql
spec:
  serviceName: "mysql"
  replicas: 3
  template:
    metadata:
      annotations:
        vault.hashicorp.com/agent-inject: "true"
        vault.hashicorp.com/role: "mysql-readonly"
        vault.hashicorp.com/agent-inject-secret-db-creds: "database/creds/mysql-readonly"
        vault.hashicorp.com/agent-inject-template-db-creds: |
          {{- with secret "database/creds/mysql-readonly" -}}
          export MYSQL_USER="{{ .Data.username }}"
          export MYSQL_PASSWORD="{{ .Data.password }}"
          {{- end }}
    spec:
      containers:
      - name: mysql
        image: mysql:8.0
        command:
        - bash
        - -c
        - |
          source /vault/secrets/db-creds
          exec mysqld --user=mysql
        volumeMounts:
        - name: data
          mountPath: /var/lib/mysql
```

**Преимущества:**
- Каждая реплика получает уникальный пароль
- Пароль автоматически ротируется (TTL 1 час)
- Audit trail: Vault логирует каждый запрос credentials

### Сценарий 3: ESO для StatefulSet

External Secrets Operator синхронизирует секреты из Vault/KMS в нативные Secret.

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: postgres-credentials
  namespace: prod
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: postgres-credentials
    creationPolicy: Owner
  data:
  - secretKey: postgres-password
    remoteRef:
      key: prod/postgres
      property: admin-password
  - secretKey: replication-password
    remoteRef:
      key: prod/postgres
      property: replication-password
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgresql
spec:
  serviceName: "postgresql"
  replicas: 3
  template:
    spec:
      containers:
      - name: postgresql
        image: postgres:16
        env:
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: postgres-credentials
              key: postgres-password
        - name: PGDATA
          value: /var/lib/postgresql/data/pgdata
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
```

### Сценарий 4: Post-install hooks для миграций

Helm hooks позволяют запускать Job с миграциями БД после обновления секретов.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ include "chart.fullname" . }}-db-migration
  annotations:
    "helm.sh/hook": post-upgrade
    "helm.sh/hook-weight": "1"
    "helm.sh/hook-delete-policy": before-hook-creation
spec:
  template:
    spec:
      containers:
      - name: migration
        image: myapp/migrations:{{ .Chart.AppVersion }}
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: {{ .Values.secret.name }}
              key: connection-string
        command: ["./migrate", "up"]
      restartPolicy: Never
  backoffLimit: 1
```

**Для StatefulSet с Vault Agent:**

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ include "chart.fullname" . }}-db-init
  annotations:
    "helm.sh/hook": post-install
    "helm.sh/hook-weight": "0"
    vault.hashicorp.com/agent-inject: "true"
    vault.hashicorp.com/role: "db-init-role"
    vault.hashicorp.com/agent-inject-secret-db-creds: "database/creds/db-init"
spec:
  template:
    spec:
      containers:
      - name: db-init
        image: myapp/migrations:latest
        command:
        - bash
        - -c
        - |
          source /vault/secrets/db-creds
          ./migrate --url="mysql://${MYSQL_USER}:${MYSQL_PASSWORD}@mysql:3306/mydb"
      restartPolicy: Never
  backoffLimit: 1
```

### Сценарий 5: Ротация секретов с rolling restart

Паттерн для автоматической перезагрузки StatefulSet при изменении Secret. Используйте **Reloader** с аннотацией `reloader.stakater.com/auto: "true"` (для автоматического определения зависимостей) или `configmap.reloader.stakater.com/reload` (явный режим).

> Полные примеры Reloader + StatefulSet (PostgreSQL, Prometheus) см. в [Reloader: сценарии использования](../../ToolsUtilities/reloader/reloader_usage_scenarios.md). Для Secret-зависимости используйте `secret.reloader.stakater.com/reload: "my-secret"`.

## Диагностика и типичные ошибки

### Типичные ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `CreateContainerConfigError` | Secret не существует в namespace | `kubectl get secrets -n <ns>`; проверьте имя в `secretKeyRef` |
| Данные на диске не совпадают с Secret | Secret был обновлён, но под не перезапущен | `kubectl rollout restart statefulset/<name>` |
| Поды не могут подключиться к БД | Пароль репликации не совпадает между репликами | Убедитесь, что все реплики используют один Secret |
| `CrashLoopBackOff` после обновления Secret | Приложение не поддерживает горячую смену пароля | Перезапустите под или используйте `rollout restart` |
| Vault Agent не рендерит credentials | Неверная роль или политика Vault | Проверьте логи Vault Agent: `kubectl logs <pod> vault-agent` |
| ESO ExternalSecret в статусе `SecretSyncError` | Недоступен KMS или неверный путь | `kubectl describe externalsecret <name>` → `status.conditions` |

### Команды для отладки

```bash
# Проверка Secret
kubectl get secret mysql-credentials -n prod -o yaml

# Проверка использования Secret в StatefulSet
kubectl get statefulset mysql -n prod -o json | \
  jq '.spec.template.spec.containers[].env[]? | select(.valueFrom.secretKeyRef)'

# Проверка логов Vault Agent (если используется)
kubectl logs mysql-0 -n prod -c vault-agent

# Проверка статуса ESO
kubectl get externalsecret -n prod
kubectl describe externalsecret postgres-credentials -n prod

# Принудительный restart StatefulSet (с сохранением данных)
kubectl rollout restart statefulset/mysql -n prod

# Проверка что PVC не удалится при restart
kubectl get pvc -l app=mysql -n prod
```

## Best Practices

1. **Разделяйте root и прикладные пароли:** Используйте отдельные Secret для `MYSQL_ROOT_PASSWORD` и паролей пользователей приложения.
2. **Монтируйте как Volume, а не ENV:** Для секретов, которые могут меняться, используйте volume mount (tmpfs) вместо ENV — это позволяет обновлять файлы без перезапуска.
3. **Используйте immutable Secret:** Для статичных паролей (TLS-сертификаты, ключи шифрования) помечайте Secret как `immutable: true`.
4. **Автоматизируйте ротацию:** Используйте Vault Database Secrets Engine или ESO для автоматической генерации паролей.
5. **Резервное копирование Secret:** При бэкапе БД бэкапируйте и Secret (или используйте внешнее хранилище Vault/KMS).
6. **Post-install hooks:** Используйте Helm hooks для миграций БД, которые должны выполниться при обновлении секретов.
7. **Не удаляйте PVC при `helm uninstall`:** Добавьте `helm.sh/resource-policy: keep` к PVC и Secret.

## Дополнительная информация

### Связь с другими компонентами

- **PostgreSQL:** Используйте `POSTGRES_PASSWORD` для первичной инициализации; для репликации — `PGPASSWORD` в `primary_conninfo`.
- **Redis:** Передавайте пароль через `--requirepass` или конфигурационный файл.
- **MongoDB:** `MONGO_INITDB_ROOT_USERNAME`/`MONGO_INITDB_ROOT_PASSWORD` для первичной инициализации.
- **Elasticsearch:** `ELASTIC_PASSWORD` для настройки безопасности кластера.

### Смотрите также

- [Основы Secret](secrets_basics.md) — определения и типы.
- [Использование Secret](using_secrets.md) — доставка в Pod.
- [Внешние менеджеры](external_managers.md) — ESO, CSI Driver, Vault.
- [Vault + Kubernetes](../../../Vault/guides/vault_kubernetes_integration.md) — полная интеграция.
- [Helm + секреты](helm_secrets.md) — управление секретами в Helm.
- [StatefulSet: практическое руководство](../../Base/StatefulSet/statefulset_practical_guide.md) — сценарии развертывания.
- [StatefulSet: лучшие практики](../../Base/StatefulSet/statefulset_best_practices.md) — рекомендации по эксплуатации.
