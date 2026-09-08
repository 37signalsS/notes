# Безопасность и лучшие практики Helm

## Определения

**Безопасность Helm** — это комплекс мер по защите конфигураций, проверке подлинности артефактов и ограничению области влияния (blast radius) при развертывании приложений в Kubernetes. Включает в себя защиту цепочки поставки (Supply Chain Security), изоляцию расширений и управление доступом.

**Лучшие практики (Best Practices)** — набор устоявшихся архитектурных подходов, обеспечивающих воспроизводимость, минимизацию конфликтов (SSA) и автоматизацию жизненного цикла (ALM) инфраструктуры.

**Blast radius** — предельный радиус разрушения (масштаб последствий) при компрометации одного секрета, плагина, RBAC-роли или шаблона. В Helm blast radius ограничивается через `--history-max`, `--atomic`, `--cleanup-on-fail`, неймспейс-изоляцию и пиннинг чартов по SHA-дигесту.

**Defence in depth (эшелонированная защита)** — принцип, согласно которому чарт должен оставаться безопасным даже при компрометации одного слоя: chart-repository, рендеринг, admission-контроллер кластера, runtime-политики пода. Helm отвечает за первые два слоя, остальные обеспечиваются инфраструктурой.

---

## Основные концепции

### 1. Архитектурная безопасность в Helm v4
В 2026 году безопасность Helm базируется на двух столпах:
- **Server-Side Apply (SSA)**: Логика слияния на стороне API-сервера Kubernetes. Позволяет точно отслеживать «владельцев» (field ownership) каждого поля. Это предотвращает случайное затирание настроек, внесенных другими контроллерами (например, Istio-инъекторами или HPA), и минимизирует права клиента.
- **WASM-песочница (WASM Sandbox)**: Плагины Helm v4 выполняются в изолированной среде WebAssembly. Это устраняет риски выполнения произвольного кода на хосте (в отличие от скриптовых плагинов v3) и обеспечивает строгий контроль доступа расширений к файловой системе и API.

### 2. Защита цепочки поставки (Sigstore/Cosign)
При использовании OCI-реестров критически важно гарантировать целостность чарта:
- **Подпись артефактов**: Использование **Cosign** для подписи образов чартов.
- **Верификация по дигесту**: Установка через `sha256` исключает риски подмены тега (tag moving).
- **Keyless-подпись**: Использование OIDC-токенов для подписи без необходимости управления долгоживущими ключами.

### 3. Стратегии управления секретами
Helm не шифрует значения в `values.yaml`. Основные подходы:
- **GitOps-подход (SOPS)**: Шифрование файлов секретов в Git с использованием **KMS** (HashiCorp Vault Transit, on-prem PKI, age, GPG) или внешнего KMS. **Cloud-KMS считается устаревшим паттерном** — для on-prem используйте Vault Transit или age с локальным ключом.
- **Runtime-подход (ESO/Vault)**: Использование **External Secrets Operator** или **Secrets Store CSI Driver**. В этом случае Helm управляет только заглушками (`ExternalSecret` / `SecretProviderClass`), а реальные данные инжектируются напрямую в поды.

### 4. Pod Security Standards (PSS) и Pod Security Admission (PSA)
Helm не контролирует runtime-политики подов — это работа кластера, но чарт должен проектироваться так, чтобы соответствовать уровню `restricted` (см. [Pod Security Context](../../Security/pod_security_context.md)). Чарт обязан:
- использовать `securityContext` с `runAsNonRoot: true` и `readOnlyRootFilesystem: true`;
- явно сбрасывать `capabilities.drop: [ALL]` и запрещать `allowPrivilegeEscalation: true`;
- задавать `seccompProfile.type: RuntimeDefault`;
- избегать `hostNetwork`, `hostPID`, `hostIPC`.

Если чарт нарушает эти требования, его нельзя устанавливать в неймспейс с PSA-меткой `restricted` — `helm install` упадёт на admission-контролле кластера, **но только при `helm upgrade --install` против живого кластера**. На этапе `helm template` и `helm lint` эти нарушения невидимы, поэтому требуется статический анализ (conftest, checkov).

### 5. Защита от drift и атомарность операций
- **`--atomic`**: при неуспехе нового релиза откатывает к предыдущему успешному. Защищает от ситуации «половина чарта применилась, половина — нет».
- **`--wait`** / **`--wait-for-jobs`**: блокирует возврат из `upgrade`, пока ресурсы не достигнут `Ready`. Без этого флага Helm завершается сразу после отправки манифестов, и ошибки rollout-а проявляются только при следующей операции.
- **`--timeout`**: защищает от зависших jobs/rollouts. Для production-чартов с Job-хуками устанавливайте не менее `10m`.
- **`--history-max N`**: ограничивает количество хранимых ревизий. По умолчанию `10`, рекомендуется `5` — каждая ревизия хранит «слепок» секретов в ConfigMap/Secret.

### 6. Безопасность зависимостей (`Chart.yaml`)
Файл `Chart.yaml` со ссылкой на внешний чарт — это вектор атаки. Безопасная практика:
- **Пинить версии явно**: `version: 0.1.2`, **не** `^0.1.0` и не `latest`.
- **Пинить SHA чарта**: Helm 4 поддерживает поле `digest` в `Chart.yaml` для OCI-зависимостей — при обновлении проверяется не только тег, но и хеш.
- **`condition`**: использовать в `requirements`/`dependencies` для опционального включения сабчартов; без `condition` сабчарт с дефолтами может установить лишние ресурсы.
- **`alias`**: переименовывает сабчарт в локальной области имён (`{{ .Chart.Name }}.foo` → `{{ .Chart.Name }}.bar`), предотвращая коллизии.
- **`import-values`**: ОСТОРОЖНО — позволяет импортировать values из сабчарта в parent. При использовании чужого чарта это создаёт скрытую зависимость от структуры `values.yaml` сабчарта. Безопаснее использовать `values` блок с явной переадресацией.

### 7. Подпись provenance (SLSA / Helm 4 attestation)
В Helm 4 chart-repository может публиковать **provenance-файл** (`*.prov`) с подписью, подтверждающей, что чарт собран из конкретного коммита конкретного репозитория. Это уровень **SLSA L3** для supply chain. `helm install --verify` проверяет наличие `*.prov` в репозитории и его подпись GPG-ключом, чей fingerprint разрешён в переменной окружения `HELM_KEYRING` или флаге `--keyring`. Проверка provenance должна быть включена в CI, иначе нет смысла её публиковать.

### 8. Безопасность WASM-плагинов
При установке плагинов из OCI-реестров всегда проверяйте их источник:
```bash
# Установка плагина по дигесту из доверенного реестра
helm plugin install oci://registry.company.com/plugins/security-checker@sha256:7f...
```

Перед установкой плагина Helm 4 запрашивает GPG-верификацию артефакта. Если GPG-ключ плагина не импортирован в keyring, установка завершится ошибкой `plugin signature verification failed` — это **не** баг, а фича. Для on-prem реестров импортируйте корпоративный ключ один раз:
```bash
gpg --no-default-keyring --keyring ~/.config/helm/keyring.gpg \
    --import plugin-signing-key.asc
```

### 9. Изоляция в air-gapped и on-prem средах
- **Локальный OCI-реестр** (Harbor, Distribution) с включённым `cosign` web-hook для автоматической подписи при push.
- **Helm 4 GPG-keyring** распространяется через Ansible/Configuration Management — без него WASM-плагины не установятся.
- **SHA-пиннинг** обязателен: без интернета невозможно проверить актуальность тега.
- **`helm dependency build` → `helm package`** выполняется на «сборочной» машине с доступом в интернет, дальше `.tgz` переносится вручную или через artifact-proxy.
- **Косign keyless НЕ работает** в air-gapped (нужен OIDC-провайдер Fulcio/Sigstore). Используйте key-based подпись с локальным GPG/age-ключом.

### 10. RBAC для Helm в CI/CD
Helm v3+ не имеет серверного компонента, поэтому использует kubeconfig пользователя. Для CI/CD создаётся **отдельный ServiceAccount** с минимальными правами. Рекомендуемая структура:
- **`deployer`** ServiceAccount в namespace `ci-cd` с ClusterRole `helm-deployer`, разрешающей `get/list/create/update/patch` только на ресурсы, которые деплоит конкретный пайплайн (Deployment, Service, ConfigMap, Secret, Job).
- **`rollbacker`** ServiceAccount с правами только на `get/list` + `helm rollback` (через Helm RBAC plugin).
- **Никаких `cluster-admin`** — даже в dev. Это устраняет риск эскалации при компрометации CI.

---

## Практические сценарии

### 1. Многоуровневая валидация (The Validation Pipeline)
Для предотвращения деплоя небезопасных конфигураций используйте цепочку проверок перед `helm upgrade`:

```bash
# 1. Линтинг (синтаксис и структура)
helm lint ./my-chart

# 2. Валидация входных данных через JSON Schema
# Автоматически выполняется Helm при наличии values.schema.json
helm template my-release ./my-chart -f values.yaml

# 3. Валидация манифестов (SSoT: kubeconform)
# Проверка на соответствие схемам Kubernetes и CRD
helm template my-release ./my-chart | kubeconform -strict -summary -

# 4. Анализ политик (Policy-as-Code)
# Поиск привилегированных контейнеров, отсутствия лимитов и др.
checkov -d . --framework helm
# ИЛИ через conftest (OPA/Rego)
helm template . | conftest test -
```

### 2. Применение принципа минимизации прав (RBAC)
В Helm v3/v4 нет серверного компонента (Tiller), поэтому безопасность зависит от прав пользователя в `kubeconfig`.

**Рекомендации:**
- **Изоляция Namespace**: Ограничивайте права Role/RoleBinding конкретным неймспейсом.
- **Ограничение глаголов**: Для CI/CD используйте права только на `get`, `list`, `create`, `update`, `patch` для конкретных ресурсов.
- **History Limits**: Ограничивайте количество ревизий (`--history-max 5`), чтобы минимизировать количество Secret-объектов Helm в кластере.

### 3. Безопасность WASM-плагинов
При установке плагинов из OCI-реестров всегда проверяйте их источник:
```bash
# Установка плагина по дигесту из доверенного реестра
helm plugin install oci://registry.company.com/plugins/security-checker@sha256:7f...
```

### 4. Использование JSON-схем (`values.schema.json`)
Обязательно определяйте типы данных и ограничения (например, `minimum` для портов), чтобы предотвратить инъекции некорректных параметров. Пример минимальной схемы:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["image", "replicas"],
  "properties": {
    "image": {
      "type": "object",
      "required": ["repository", "tag"],
      "properties": {
        "repository": {"type": "string", "pattern": "^[a-z0-9./-]+$"},
        "tag": {"type": "string", "pattern": "^[a-zA-Z0-9._-]{1,128}$"}
      }
    },
    "replicas": {"type": "integer", "minimum": 1, "maximum": 50},
    "service": {
      "type": "object",
      "properties": {
        "port": {"type": "integer", "minimum": 1, "maximum": 65535}
      }
    }
  }
}
```

`pattern` блокирует инъекцию shell-метасимволов и попытки обхода путей.

### 5. Hardened `securityContext` в шаблонах
Все ресурсы `Deployment`/`StatefulSet` в чарте должны включать жёсткий securityContext (SSoT: [Pod Security Context](../../Security/pod_security_context.md)):

```yaml
spec:
  template:
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 65532
        runAsGroup: 65532
        fsGroup: 65532
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: app
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop: ["ALL"]
        resources:
          limits:
            cpu: "500m"
            memory: "256Mi"
          requests:
            cpu: "100m"
            memory: "128Mi"
```

Добавьте unit-тест helm-unittest, который **обязывает** наличие этих полей — без них тест падает (SSoT: [unit_testing.md](./unit_testing.md)).

### 6. Защита от инъекций через `--set`
`--set` парсит значения как выражения Helm template-движка. Злоумышленник, контролирующий переменные окружения CI (например, через `PR_TITLE`), может выполнить произвольный шаблон. Защита:

```bash
# НЕБЕЗОПАСНО: значение попадает в template как строка
helm upgrade my-release ./my-chart --set image.tag="$PR_TITLE"

# БЕЗОПАСНО: значения только из проверенного файла
helm upgrade my-release ./my-chart -f values-staging.yaml
```

Дополнительно, в шаблонах оборачивайте пользовательский ввод в кавычки:
```yaml
image: "{{ .Values.image.repository }}:{{ .Values.image.tag | quote }}"
```

Используйте функцию `quote` (Go: `printf "%q"`) — это экранирует YAML-спецсимволы и предотвращает инъекцию новых полей.

### 7. SHA-пиннинг зависимостей
В `Chart.yaml` для OCI-зависимостей указывайте дигест:

```yaml
dependencies:
- name: postgresql
  version: "1.2.3"
  repository: oci://registry.company.com/charts
  digest: sha256:abc123...   # Helm 4.0+
```

`helm dependency build` упадёт, если дигест не совпадёт. Это **единственный** способ гарантировать, что `helm dependency update` не подтянет скомпрометированную новую версию под тем же тегом.

Дополнительно: используйте `helm dep build` (без `update`) — он откажется обновлять, если дигест не совпадает.

### 8. Атомарный деплой и защита от drift
```bash
helm upgrade --install my-release ./my-chart \
  --atomic \
  --timeout 10m \
  --wait \
  --wait-for-jobs \
  --history-max 5 \
  --cleanup-on-fail \
  -f values-prod.yaml
```

- `--atomic` — откат при неуспехе rollout.
- `--wait` + `--wait-for-jobs` — дождаться готовности подов и Job-хуков.
- `--timeout 10m` — избежать зависания CI.
- `--history-max 5` — уменьшить хранение секретов в ConfigMap `sh.helm.release.v1.my-release`.
- `--cleanup-on-fail` — удалить ресурсы нового релиза при ошибке (только в сочетании с `--atomic`).

### 9. RBAC ServiceAccount для Helm-оператора
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: helm-deployer
  namespace: ci-cd
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: helm-deployer-role
  namespace: production
rules:
- apiGroups: ["apps", "batch"]
  resources: ["deployments", "statefulsets", "jobs"]
  verbs: ["get", "list", "create", "update", "patch"]
- apiGroups: [""]
  resources: ["configmaps", "secrets", "services"]
  verbs: ["get", "list", "create", "update", "patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: helm-deployer-binding
  namespace: production
subjects:
- kind: ServiceAccount
  name: helm-deployer
  namespace: ci-cd
roleRef:
  kind: Role
  name: helm-deployer-role
  apiGroup: rbac.authorization.k8s.io
```

См. подробнее про [ограничения RBAC, OPA Gatekeeper, Kyverno, ValidatingAdmissionPolicy](../../Security/rbac/limitations_opa.md) и [управление секретами](../../Security/application_secrets_management.md).

### 10. Безопасность hook-ресурсов
Helm-hooks (`pre-install`, `pre-upgrade`, `post-delete`) выполняют Job-ы с правами ServiceAccount релиза. Это критический вектор атаки:

- Назначайте hook-Job'ам **отдельный ServiceAccount** с минимальными правами.
- Для `pre-install` (инициализация БД) используйте **initContainer** вместо Job-хука — он выполняется с тем же SA, что и под, проще аудитируется.
- **`post-delete`** — самый опасный хук: невозможно откатить, выполняется на удалении. Не помещайте в него код, изменяющий внешние системы.
- **Запрещайте `hostNetwork: true`** в hook-шаблонах.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: "{{ .Release.Name }}-migrate"
  annotations:
    "helm.sh/hook": pre-upgrade
    "helm.sh/hook-weight": "-5"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  template:
    spec:
      serviceAccountName: {{ .Release.Name }}-migrator   # отдельный SA
      restartPolicy: Never
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: migrate
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop: ["ALL"]
```

### 11. `.helmignore` и предотвращение утечки
При упаковке чарта (`helm package`) **все** файлы из директории включаются в `.tgz`, если не перечислены в `.helmignore`. Утечка `.env` или `.git/` в OCI-артефакт приводит к утечке секретов и истории коммитов.

Минимальный `.helmignore`:
```
.git/
.gitignore
.helmignore
.env
.env.*
*.swp
*.bak
secrets/
README.md
ci/
tests/
.github/
.gitlab-ci.yml
Jenkinsfile
```

Дополнительно, при публикации в OCI: проверяйте `helm package --debug` и `tar -tzf chart-0.1.0.tgz` перед `helm push`.

### 12. Подпись и верификация чарта в on-prem
```bash
# Генерация ключа подписи (один раз)
gpg --quick-gen-key "Helm Release Engineer <releng@company.com>" default default 0

# Упаковка с автоматической подписью provenance
helm package ./my-chart --sign --key releng@company.com --keyring ~/.gnupg/secring.gpg

# Публикация вместе с .prov
helm push my-chart-0.1.0.tgz oci://registry.company.com/charts
helm push my-chart-0.1.0.prov oci://registry.company.com/charts

# Установка с верификацией — ОБЯЗАТЕЛЬНО в CI
helm install my-release oci://registry.company.com/charts/my-chart \
  --version 0.1.0 \
  --verify \
  --keyring ~/.gnupg/pubring.gpg
```

В CI/CD эту последовательность нужно завернуть в pre-deploy stage. Сценарий подробнее (включая keyless через cosign + OIDC) — в [Advanced scenarios](./scenarios.md).

### 13. Hook и `cleanup-on-fail` для отката
При неуспехе `helm upgrade` с `--atomic` Helm:
1. Создаёт новую ревизию (релиз №N+1).
2. Пытается применить.
3. При ошибке вызывает `helm rollback` на релиз №N.
4. С `--cleanup-on-fail` удаляет **ресурсы** нового релиза, оставив запись.

**Проблема:** если новый релиз добавил ресурс, которого не было в №N, после rollback новый ресурс остаётся. Решение — pre-upgrade Job-хук с **dry-run проверкой**:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: "{{ .Release.Name }}-preflight"
  annotations:
    "helm.sh/hook": pre-upgrade
    "helm.sh/hook-weight": "-10"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: preflight
        image: "{{ .Values.tools.image }}:{{ .Values.tools.tag }}"
        command: ["sh", "-c", "kubectl auth can-i create deployment --as=system:serviceaccount:prod:helm-deployer"]
```

### 14. Включение Pod Security Standards на уровне namespace
Чарт не может управлять PSA-метками namespace, но должен проверять, что target namespace удовлетворяет требуемому уровню:

```bash
# Проверить текущий уровень namespace
kubectl get ns production -o jsonpath='{.metadata.labels}{"\n"}'
# Должно быть: pod-security.kubernetes.io/enforce=restricted
```

Если метки нет — namespace работает в режиме `privileged` (по умолчанию), что **недопустимо** для production. Helm 4 (через `pre-install` hook или admission) может это валидировать.

### 15. Чек-лист безопасности чарта
Используйте перед публикацией каждой версии:

- [ ] `helm lint` проходит без warning.
- [ ] `values.schema.json` покрывает все обязательные поля.
- [ ] `helm template | kubeconform -strict` — нет ошибок схемы.
- [ ] `helm template | conftest test` — все Rego-политики pass.
- [ ] Все контейнеры имеют `securityContext` (см. сценарий 5).
- [ ] Все `image:` пиннятся по тегу + дигесту, не `latest`.
- [ ] Все зависимости в `Chart.yaml` пиннятся по версии + дигесту.
- [ ] `.helmignore` исключает `.git/`, `.env*`, `secrets/`, `ci/`, `tests/`.
- [ ] Для OCI-релиза: подпись `*.prov` создана, верифицируется `helm install --verify`.
- [ ] `--atomic --wait --timeout 10m --history-max 5` — обязательные флаги в CI.
- [ ] `cosign verify-blob --key cosign.pub my-chart-0.1.0.tgz` — успешен.
- [ ] В README описаны security-relevant values (`imagePullSecrets`, `serviceAccount`).
- [ ] Нет `--set` с пользовательским вводом (используется только `-f`).

### 16. Troubleshooting типовых security-ошибок

| Симптом | Причина | Решение |
|---|---|---|
| `forbidden: violates PodSecurity "restricted:..."` | Чарт рендерит `privileged` или `allowPrivilegeEscalation: true` | Исправить шаблон (см. сценарий 5); не отключать PSA-метку namespace |
| `no available release name found` после rollback | `--history-max` слишком мал, либо релиз в `failed` state | `helm history my-release`, `helm rollback my-release <rev>` |
| `plugin signature verification failed` (Helm 4) | GPG-ключ плагина не импортирован в keyring | `gpg --import plugin-key.asc` или флаг `--verify=false` (только для dev) |
| `Failed to install: failed to download` (air-gapped) | Чарт тянет зависимость, отсутствующую в локальном registry | `helm dep build` + `helm package` на онлайн-машине; перенести `.tgz` |
| `value with type string required` | Пользователь передал число/объект через `--set` | Использовать `-f values.yaml` или строго типизированную JSON-схему |
| `template: ... cannot unmarshal ... into int` | `values.schema.json` не совпадает с реальным типом | Обновить схему, добавить helm-unittest на типы |
| `OCI artifact digest mismatch` | Тег чарта переиспользован, дигест изменился | Указать точный дигест `@sha256:...`; обновить `Chart.yaml` |
| `external secret sync failed` | ESO/Vault недоступен; `SecretStore` не настроен | Чарт валиден, но runtime-инъекция упала — проверить `ExternalSecret` status |
| `denied the request: ... not permitted by policy` (OPA/Kyverno) | Policy блокирует нерекомендуемые security settings | Скорректировать шаблон; не отключать политику |
| `Error: UPGRADE FAILED: another operation (install/upgrade/rollback) is in progress` | Параллельный Helm-запуск на одном релизе | Включить `--wait` + `--atomic`; в CI добавить mutex по имени релиза |

---

## Дополнительная информация

- **[Обзор Helm](../helm_overview.md)** — архитектура v4, SSA и установка.
- **[Команды и рабочий процесс](../helm_commands_and_workflow.md)** — интроспекция и управление релизами.
- **[Плагины Helm](../helm_plugins.md)** — детальный разбор WASM-расширений.
- **[Продвинутые сценарии](./scenarios.md)** — подпись через Cosign и Post-rendering.
- **[Юнит-тестирование](./unit_testing.md)** — BDD-тесты helm-unittest, включая `securityContext` ассерты.
- **[Хуки и тестирование](../helm_hooks_and_tests.md)** — управление жизненным циклом ресурсов.
- **[Шаблонизация Helm](../helm_templating.md)** — функции, безопасность выражений.
- **[Паттерны и устранение неисправностей](./patterns_troubleshooting.md)** — диагностика типовых ошибок.
- **[Использование kubeconform](../../ToolsUtilities/kubeconform_overview.md)** — детальное руководство по валидации манифестов.
- **[Pod Security Context](../../Security/pod_security_context.md)** — SSoT по `securityContext`, PSS, PSA.
- **[Ограничения RBAC и Policy-as-Code](../../Security/rbac/limitations_opa.md)** — RBAC, OPA Gatekeeper, Kyverno, ValidatingAdmissionPolicy.
- **[Управление секретами в приложениях](../../Security/application_secrets_management.md)** — Secret, SOPS, Sealed Secrets, ESO, Vault, CSI Driver.
- **[Сравнение версий Helm](../helm_v2_vs_v3.md)** — эволюция безопасности от Tiller до SSA.
