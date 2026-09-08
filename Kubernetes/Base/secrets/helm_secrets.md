# Управление секретами в Helm

## Определения

**Helm** — пакетный менеджер для Kubernetes, позволяющий шаблонизировать, версионировать и деплоить манифесты через чарты. Secrets management в Helm охватывает механизмы безопасной передачи конфиденциальных данных в шаблоны без их сохранения в открытом виде в Git.

**helm-secrets** — плагин Helm, интегрирующий **Mozilla SOPS** для шифрования/дешифрования файлов значений на лету. Позволяет хранить зашифрованные `secrets.yaml` в Git и передавать их в `helm upgrade` без раскрытия данных.

**existingSecret** — паттерн, при котором Helm-чарт ссылается на уже существующий объект `Secret` в Kubernetes, вместо его создания. Это позволяет отделить управление секретами от жизненного цикла чарта и использовать внешние системы (ESO, Sealed Secrets, Vault) для доставки секретов.

## Основные концепции

### Почему секреты в values.yaml — это анти-паттерн

Хранение секретов в `values.yaml` или через `--set` опасно по нескольким причинам:

| Риск | Описание |
| :--- | :--- |
| **Git история** | Секреты попадают в Git-репозиторий и остаются в истории навсегда (даже после удаления файла) |
| **Helm hooks** | При `helm upgrade` предыдущие значения хранятся в ConfigMap релиза (`sh.helm.release.v1.*`) |
| **Логирование** | `helm upgrade --set secret=value` виден в логах CI/CD, `ps aux`, `.bash_history` |
| **Kubernetes events** | Значения переменных окружения видны через `kubectl describe pod` |
| **Helm history** | `helm history` и `helm get values` показывают предыдущие значения |

**Рекомендация:** секреты никогда не хранятся в `values.yaml` и не передаются через `--set`. Используйте `existingSecret`, `helm-secrets` или внешние менеджеры. Подробнее о рисках см. в [Параметризация](../../../Kubernetes/ToolsUtilities/Helm/templating/scenarios/parameterization.md) (раздел "Безопасность: секреты в values.yaml").

### Модели управления секретами в Helm

| Модель | Механизм | Безопасность | Сложность |
| :--- | :--- | :--- | :--- |
| **existingSecret** | Ссылка на внешний Secret | Высокая | Низкая |
| **helm-secrets + SOPS** | Шифрование файлов значений | Высокая | Средняя |
| **External Secrets Operator** | Синхронизация из KMS | Высокая | Средняя |
| **Sealed Secrets** | Шифрование для конкретного кластера | Средняя | Низкая |
| **Vault Agent Injector** | Sidecar с рендерингом | Очень высокая | Высокая |

### Паттерн existingSecret

Наиболее безопасный встроенный способ: Helm-чарт определяет опциональный параметр `existingSecret`, который ссылается на ранее созданный объект `Secret`.

**Реализация в Chart.yaml:**

```yaml
# values.yaml
secret:
  create: true          # создавать ли Secret через Helm
  name: ""              # имя внешнего Secret (если create: false)
  data: {}
    # username: admin
    # password:changeme
```

**Реализация в шаблоне:**

```yaml
{{- if .Values.secret.create }}
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "chart.fullname" . }}
  labels:
    {{- include "chart.labels" . | nindent 4 }}
type: Opaque
data:
  {{- range $key, $value := .Values.secret.data }}
  {{ $key }}: {{ $value | b64enc | quote }}
  {{- end }}
{{- end }}
---
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
      - name: app
        env:
        {{- if .Values.secret.create }}
        - name: DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: {{ include "chart.fullname" . }}
              key: password
        {{- else }}
        - name: DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: {{ .Values.secret.name }}
              key: password
        {{- end }}
```

**Использование:**

```bash
# Вариант 1: секрет управляется внешней системой
helm upgrade --install my-app ./chart \
  --set secret.create=false \
  --set secret.name=external-db-credentials

# Вариант 2: секрет создаётся Helm (только для dev/test!)
helm upgrade --install my-app ./chart \
  --set secret.create=true \
  --set secret.data.password=my-secure-password
```

## Практические сценарии

### Интеграция helm-secrets с SOPS

**Установка:**

```bash
# Установка плагина
helm plugin install https://github.com/jkroepke/helm-secrets

# Проверка версии
helm secrets --version
```

**Создание зашифрованного файла значений:**

```bash
# 1. Создайте файл secrets.yaml в открытом виде
cat > secrets.yaml <<EOF
database:
  password: "super-secret-password"
api:
  key: "7f5a8c3e-1234-5678-9abc-def012345678"
EOF

# 2. Зашифруйте файл через SOPS (age)
sops -e -i secrets.yaml

# 3. Зашифрованный файл безопасен для Git
git add secrets.yaml
```

**Деплой с расшифровкой на лету:**

```bash
# Расшифровка и деплой в одной команде
helm secrets upgrade --install my-app ./chart \
  -f values.yaml \
  -f secrets.yaml

# Только рендеринг (без применения)
helm secrets template my-app ./chart \
  -f values.yaml \
  -f secrets.yaml
```

**Конфигурация .sops.yaml для чарта:**

```yaml
# .sops.yaml в корне репозитория
creation_rules:
  - path_regex: secrets\.yaml$
    age: age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p
  - path_regex: values.*\.yaml$
    age: age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p
```

### Multi-file values с секретами

Паттерн разделения конфигурации и секретов:

```
chart/
  values.yaml           # открытое: replicaCount, image, resources
  values-secrets.yaml   # зашифровано: пароли, ключи (через helm-secrets)
```

```bash
# Деплой с обоими файлами
helm secrets upgrade --install my-app ./chart \
  -f chart/values.yaml \
  -f chart/values-secrets.yaml
```

### Интеграция с External Secrets Operator (ESO)

Паттерн: ESO создаёт Secret, Helm ссылается через existingSecret.

```yaml
# external-secrets.yaml (управляется ESO)
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: db-credentials
  namespace: prod
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: db-credentials
    creationPolicy: Owner
  data:
  - secretKey: password
    remoteRef:
      key: secret/data/prod/myapp
      property: password
```

```bash
# Helm-деплой со ссылкой на внешний Secret
helm upgrade --install my-app ./chart \
  -f values.yaml \
  --set secret.create=false \
  --set secret.name=db-credentials
```

### Интеграция с Sealed Secrets

Паттерн: зашифрованный Secret управляется через Sealed Secrets controller.

```bash
# 1. Создайте зашифрованный Secret
kubectl create secret generic db-credentials \
  --from-literal=password=my-password \
  --dry-run=client -o yaml | \
  kubeseal --format yaml > sealed-secret.yaml

# 2. Добавьте SealedSecret в Helm-чарт как манифест
# templates/sealed-secret.yaml

# 3. Деплой
helm upgrade --install my-app ./chart -f values.yaml
```

### Интеграция с HashiCorp Vault (Vault Agent Injector)

Паттерн: Vault Agent внедряется как sidecar через аннотации в Pod.

```yaml
# values.yaml
vault:
  enabled: true
  role: "myapp-role"
  secrets:
    - secretPath: "secret/data/prod/myapp"
      secretKey: "password"
      mountPath: "/vault/secrets"
```

```yaml
# templates/deployment.yaml
spec:
  template:
    metadata:
      annotations:
        {{- if .Values.vault.enabled }}
        vault.hashicorp.com/agent-inject: "true"
        vault.hashicorp.com/role: {{ .Values.vault.role | quote }}
        {{- range .Values.vault.secrets }}
        vault.hashicorp.com/agent-inject-secret-{{ .secretKey }}: {{ .secretPath | quote }}
        {{- end }}
        {{- end }}
```

## Диагностика и типичные ошибки

### Типичные ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Error: secret "xxx" not found` | `existingSecret` указывает на несуществующий Secret | Создайте Secret перед Helm-деплоем; проверьте `kubectl get secrets -n <ns>` |
| `secrets "xxx" is forbidden` | Нет прав RBAC на чтение Secret | Добавьте Role/RoleBinding для ServiceAccount Helm |
| `could not find a ready tunnel` | Vault Agent Injector webhook недоступен | Проверьте Vault Agent Injector: `kubectl get pods -n vault` |
| `sops metadata not found` | Файл не зашифрован через SOPS | Выполните `sops -e -i <file>` перед коммитом |
| `helm-secrets: file not found` | Неверный путь к зашифрованному файлу | Проверьте путь в команде `helm secrets upgrade` |
| Secret удаляется при `helm uninstall` | Secret создан Helm и имеет `ownerReference` | Используйте `helm.sh/resource-policy: keep` или `existingSecret` |

### Проверка после деплоя

```bash
# Проверка, что Secret создан
kubectl get secret my-secret -n <namespace>

# Проверка, что Secret содержит правильные ключи
kubectl get secret my-secret -n <namespace> -o jsonpath='{.data}' | jq 'keys'

# Проверка использования Secret в Pod
kubectl get pod -n <namespace> -o json | \
  jq '.items[] | select(.spec.containers[].envFrom[]?.secretRef.name == "my-secret") | .metadata.name'

# Проверка логов helm-secrets
helm secrets upgrade --install my-app ./chart -f values.yaml -f secrets.yaml --debug
```

## Best Practices

### Рекомендации

1. **Разделяйте файлы:** `values.yaml` для открытых настроек, `secrets.yaml` для зашифрованных (через `helm-secrets`).
2. **Используйте existingSecret:** Если секрет уже создан внешней системой (ESO, Vault, Sealed Secrets), ссылайтесь на него через `existingSecret`.
3. **Никогда не коммитьте открытые секреты:** Используйте `.gitignore` для временных файлов с секретами; `.sops.yaml` для шаблонов шифрования.
4. **Отключайте автомонтирование SA:** `automountServiceAccountToken: false` для сервисов, не обращающихся к API Kubernetes.
5. **Используйте helm.sh/resource-policy:** Для Secret'ов, которые не должны удаляться при `helm uninstall`:
   ```yaml
   annotations:
     helm.sh/resource-policy: keep
   ```
6. **Валидируйте через CI/CD:** Запускайте `helm secrets template` в CI для проверки без фактического деплоя.
7. **Ротируйте ключи SOPS:** Регулярно обновляйте ключи шифрования через `sops updatekeys`.
8. **Документируйте:** Указывайте в `README.md` чарта, какие секреты требуются и как их создавать.

## Дополнительная информация

### Сравнение с другими подходами

| Критерий | Helm + existingSecret | helm-secrets + SOPS | ESO | Sealed Secrets |
| :--- | :--- | :--- | :--- | :--- |
| Хранение секретов | Вне Helm | В Git (зашифровано) | В KMS | В Git (зашифровано) |
| Автоматическая ротация | Нет | Нет | Да | Нет |
| Зависимости | Нет | SOPS, age/KMS | ESO Operator | Sealed Secrets Controller |
| GitOps совместимость | Да | Да | Да | Да |
| Стоимость | Нулевая | Нулевая | Зависит от KMS | Нулевая |

### Смотрите также

- [Основы Secret](secrets_basics.md) — определения и типы.
- [Создание Secret](creating_secrets.md) — способы формирования объектов.
- [Безопасность Secret](security.md) — методы защиты.
- [Внешние менеджеры](external_managers.md) — ESO, CSI Driver, Vault.
- [Sealed Secrets](../../Security/sealed_secrets_overview.md) — шифрование для GitOps.
- [SOPS](../../../Security/Tools/sops_overview.md) — шифрование файлов.
- [GitOps: управление секретами](../../../GitOps/secrets_encryption.md) — сравнение подходов.
