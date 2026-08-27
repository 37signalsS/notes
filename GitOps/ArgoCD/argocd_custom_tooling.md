# ArgoCD — расширение функционала через Custom Tooling

**ArgoCD** обладает встроенной поддержкой популярных инструментов (Helm, Kustomize, Jsonnet), однако для специфических задач (использование QBEC, Helmwave, Helmfile) или кастомной генерации манифестов предусмотрен механизм **Custom Tooling** на базе **Config Management Plugins (CMP)**.

> **Актуальность (2026):** CMP v2 — рекомендуемый архитектурный подход для расширения ArgoCD. CMP v1 (legacy) полностью deprecated начиная с v2.8. Sidecar-модель обеспечивает изоляцию зависимостей и безопасность. Проект активно развивается, плагины доступны для большинства инструментов экосистемы.

## Предварительные требования

1. **ArgoCD v2.4+:** CMP v2 поддерживается начиная с v2.4. Рекомендуется v2.8+ для полной функциональности.
2. **Доступ к `argocd-repo-server`:** Нужны права на модификацию Deployment (kubectl edit/deploy).
3. **Container Registry:** Для хранения собственных образов sidecar (BYOI).
4. **Понимание RBAC:** Настройка прав для CMP sidecar и init-контейнеров.

## Определения

**Config Management Plugin (CMP) v2** — современная архитектура плагинов в ArgoCD (v2.4+), работающая в изолированных **sidecar-контейнерах** пода `argocd-repo-server`. Это обеспечивает безопасность и независимость зависимостей.

**Discovery (Обнаружение)** — механизм автоматического определения подходящего плагина для конкретной директории в Git на основе наличия файлов или аннотаций.

**Фаза инициализации (Init Phase)** — этап подготовки окружения (скачивание сабчартов, расшифровка секретов, запуск `npm install`).

**Фаза генерации (Generate Phase)** — выполнение команды, результатом которой должен быть поток (stream) валидных YAML-манифестов Kubernetes.

**Фаза валидации (Validate Phase)** — проверка корректности манифестов перед применением.

**Health Check** — проверка состояния ресурса после синхронизации (выполняется Lua-скриптами ArgoCD).

**QBEC** — инструмент на базе Jsonnet для описания объектов Kubernetes для нескольких окружений.

**git-crypt** — утилита для прозрачного шифрования файлов в Git.

**Helmfile** — декларативный оркестратор для управления несколькими Helm-чартами.

**Helmwave** — современный оркестратор для Helm с поддержкой зависимостей между чартами.

## Основные концепции

### Архитектура CMP v2

```
┌─────────────────────────────────────────────────────────────────────┐
│          CMP v2: Архитектура sidecar-плагинов                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  argocd-repo-server Pod                                      │  │
│  │  ┌──────────────────┐  ┌──────────────────┐                │  │
│  │  │  repo-server     │  │  CMP Sidecar     │                │  │
│  │  │  (main container)│◀▶│  (plugin)        │                │  │
│  │  │  - git clone      │  │  - argocd-cmp-   │                │  │
│  │  │  - helm template  │  │    server         │                │  │
│  │  │  - kustomize      │  │  - my-tool        │                │  │
│  │  └──────────────────┘  └──────────────────┘                │  │
│  │         │                       │                            │  │
│  │         ▼                       ▼                            │  │
│  │  ┌──────────────────────────────────────┐                  │  │
│  │  │  /var/run/argocd (shared volume)     │                  │  │
│  │  │  - UNIX socket for communication     │                  │  │
│  │  │  - Generated manifests (YAML)        │                  │  │
│  │  └──────────────────────────────────────┘                  │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

В современных версиях ArgoCD плагины больше не настраиваются через глобальный ConfigMap. Вместо этого используется модель Sidecar:

1.  **Repo Server**: Основной контейнер клонирует репозиторий.
2.  **CMP Sidecar**: Контейнер с бинарным файлом `argocd-cmp-server` и инструментами (helm, sops, qbec).
3.  **Взаимодействие**: Контейнеры общаются через UNIX-сокет в разделяемом томе `/var/run/argocd`.

### Методы доставки инструментов

- **Custom Image (BYOI)**: Сборка собственного образа sidecar со всеми предустановленными утилитами. Рекомендуется для Production.
- **Init-containers**: Копирование бинарных файлов в `emptyDir` том, который монтируется в sidecar. Позволяет быстро менять версии инструментов без пересборки образов.

### Переменные окружения

ArgoCD передает в процесс плагина стандартные переменные:
- `ARGOCD_APP_NAME`: Имя приложения.
- `ARGOCD_APP_NAMESPACE`: Целевой namespace.
- `ARGOCD_APP_REVISION`: Хеш коммита или тег.
- `KUBE_VERSION` / `KUBE_API_VERSIONS`: Параметры целевого кластера.
- Кастомные переменные из секции `spec.source.plugin.env`.

### Жизненный цикл CMP

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Discovery  │───▶│    Init     │───▶│  Generate   │───▶│  Validate   │
│  (поиск     │    │  (подготовка│    │  (генерация │    │  (проверка  │
│   плагина)  │    │   окружения)│    │  манифестов)│    │  YAML)      │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

1. **Discovery:** ArgoCD сканирует файлы в директории приложения. Если найден `plugin.yaml` или файл из `discover.fileName`, активируется плагин.
2. **Init:** Выполняется `init`-команда плагина (например, `npm install`, `helm dependency build`).
3. **Generate:** Выполняется `generate`-команда. Результат — YAML-манифесты на stdout.
4. **Validate:** Опционально выполняется `validate`-команда для проверки манифестов.

### Безопасность CMP

| Аспект | Рекомендация |
| :--- | :--- |
| **SecurityContext** | Запуск от непривилегированного пользователя (runAsNonRoot: true) |
| **RBAC** | Минимальные права для sidecar (read-only filesystem) |
| **Network** | Ограничение сетевого доступа (NetworkPolicy) |
| **Image** | Использование Distroless или Alpine образов |
| **Secrets** | Не хранить секреты в образах; использовать Vault/Secrets |

## Практические сценарии

### Сценарий 1: Интеграция QBEC (CMP v2)

QBEC позволяет эффективно управлять Helm-чартами через Jsonnet.

**1. Настройка Sidecar в Deployment `argocd-repo-server`:**

```yaml
containers:
- name: qbec-plugin
  image: splunk/qbec:v0.15.2
  command: [/var/run/argocd/argocd-cmp-server]
  volumeMounts:
    - name: var-files
      mountPath: /var/run/argocd
    - name: plugins
      mountPath: /home/argocd/cmp-server/config
```

**2. Конфигурация `plugin.yaml`:**
Этот файл монтируется в `/home/argocd/cmp-server/config/plugin.yaml`.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ConfigManagementPlugin
metadata:
  name: qbec
spec:
  discover:
    fileName: "qbec.yaml"
  generate:
    command: ["qbec"]
    args: ["show", "$ENVIRONMENT", "--force:k8s-namespace", "$ARGOCD_APP_NAMESPACE"]
```

### Сценарий 2: Использование git-crypt для секретов

`git-crypt` требует расшифровки репозитория на этапе клонирования. Для этого используется скрипт-обертка над `git` в основном контейнере `repo-server`.

**1. Скрипт-обертка `git-wrapper.sh`:**
```bash
#!/bin/sh
$(dirname $0)/git.bin "$@"
ec=$?
# Выполняем unlock только при fetch, если есть .git-crypt
[ "$1" = fetch ] && [ -d .git-crypt ] || exit $ec
GNUPGHOME=/app/config/gpg/keys git-crypt unlock 2>/dev/null
exit $ec
```

**2. Настройка GPG ключей:**
Ключи импортируются через Kubernetes Secret и пробрасываются в поды:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: argocd-gpg-keys-secret
stringData:
  8CB8B24F50B4797D: |-
    -----BEGIN PGP PRIVATE KEY BLOCK-----
    ...
```

### Сценарий 3: Интеграция helm-secrets и SOPS

Позволяет использовать зашифрованные `secrets.yaml` в Helm-чартах.

**plugin.yaml для sidecar:**
```yaml
spec:
  discover:
    fileName: "secrets.yaml"
  generate:
    command: ["sh", "-c"]
    args: ["helm secrets template $ARGOCD_APP_NAME . -f values.yaml -f secrets.yaml"]
```

### Сценарий 4: Интеграция Helmfile и Helmwave (CMP v2)

Для этих инструментов требуется настройка RBAC, так как они могут обращаться к API Kubernetes для проверки состояния ресурсов.

**Пример настройки Sidecar (values.yaml для ArgoCD Chart):**
```yaml
repoServer:
  extraContainers:
    - name: helmfile-cmp
      command: [/var/run/argocd/argocd-cmp-server]
      image: ghcr.io/helmfile/helmfile:v0.150.0
      volumeMounts:
        - name: var-files
          mountPath: /var/run/argocd
        - name: plugins
          mountPath: /home/argocd/cmp-server/config
        - name: helm-bin
          mountPath: /usr/local/bin
  volumes:
    - name: helm-bin
      emptyDir: {}
```

**Важный нюанс Helmwave:** Инструмент чувствителен к контексту кластера. Убедитесь, что плагину доступны `KUBECONFIG` или `ServiceAccount` с правами на чтение ресурсов в целевых Namespaces.

### Сценарий 5: Интеграция ArgoCD Vault Plugin (AVP) (CMP v2)

АргоД Vault Plugin (AVP) позволяет подставлять секреты из HashiCorp Vault, AWS Secrets Manager, GCP Secret Manager в манифесты.

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
```yaml
spec:
  template:
    spec:
      containers:
      - name: avp
        command: [/var/run/argocd/argocd-cmp-server]
        image: argoproj/argocd:v2.10.0
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

**3. Использование в манифестах:**
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

**4. Активация плагина в Application:**
```yaml
spec:
  source:
    path: manifests
    plugin:
      name: argocd-vault-plugin
      env:
        - name: AVP_KV_VERSION
          value: "2"
        - name: VAULT_ADDR
          value: "https://vault.example.com"
```

### Сценарий 6: Сборка собственного образа (BYOI)

Для Production рекомендуется собирать собственный образ sidecar со всеми необходимыми инструментами.

**Dockerfile:**
```dockerfile
FROM alpine:3.19

RUN apk add --no-cache \
    git \
    curl \
    jq \
    yq \
    helm \
    kustomize \
    && wget -O /usr/local/bin/qbec https://github.com/splunk/qbec/releases/download/v0.15.2/qbec_linux_amd64 \
    && chmod +x /usr/local/bin/qbec

COPY plugin.yaml /home/argocd/cmp-server/config/plugin.yaml
COPY argocd-cmp-server /usr/local/bin/argocd-cmp-server

CMD ["/usr/local/bin/argocd-cmp-server"]
```

**Сборка и пуш:**
```bash
docker build -t my-registry/argocd-cmp-custom:v1.0 .
docker push my-registry/argocd-cmp-custom:v1.0
```

### Сценарий 7: Настройка нескольких плагинов

ArgoCD поддерживает несколько плагинов одновременно. Каждый плагин — отдельный sidecar.

**values.yaml для ArgoCD Helm Chart:**
```yaml
repoServer:
  extraContainers:
    - name: qbec-plugin
      image: splunk/qbec:v0.15.2
      command: [/var/run/argocd/argocd-cmp-server]
      volumeMounts:
        - name: var-files
          mountPath: /var/run/argocd
        - name: plugins
          mountPath: /home/argocd/cmp-server/config
    - name: helmfile-cmp
      image: ghcr.io/helmfile/helmfile:v0.150.0
      command: [/var/run/argocd/argocd-cmp-server]
      volumeMounts:
        - name: var-files
          mountPath: /var/run/argocd
        - name: helmfile-plugins
          mountPath: /home/argocd/cmp-server/config
  volumes:
    - name: var-files
      emptyDir: {}
    - name: plugins
      emptyDir: {}
    - name: helmfile-plugins
      emptyDir: {}
```

### Сценарий 8: Кастомные Health Checks для CMP-ресурсов

Для проверки здоровья ресурсов, создаваемых CMP, используйте Lua-скрипты в `argocd-cm`:

```yaml
data:
  resource.customizations.health.argoproj.io_Application: |
    hs = {}
    hs.status = "Progressing"
    hs.message = "Waiting for application"
    if obj.status ~= nil then
      if obj.status.health ~= nil then
        hs.status = obj.status.health.status
        if obj.status.health.message ~= nil then
          hs.message = obj.status.health.message
        end
      end
    end
    return hs
```

### Сценарий 9: Мониторинг производительности CMP

**Prometheus метрики для CMP:**
```yaml
# argocd-cm ConfigMap
data:
  metrics.enabled: "true"
```

**Ключевые метрики:**
- `argocd_app_reconcile_total` — количество реконсиляций
- `argocd_app_sync_total` — количество синхронизаций
- `argocd_app_health_status` — статус здоровья

## Сравнение CMP v1 и CMP v2

| Характеристика | CMP v1 (Legacy) | CMP v2 (Modern) |
| :--- | :--- | :--- |
| **Изоляция** | Отсутствует (общие зависимости). | Полная (sidecar-контейнеры). |
| **Место конфигурации** | ConfigMap `argocd-cm`. | Файл `plugin.yaml` в sidecar. |
| **Масштабируемость** | Низкая. | Высокая (независимые плагины). |
| **Безопасность** | Общие права Repo Server. | Уникальные SecurityContext и RBAC. |
| **Управление версиями** | Версия = версия ArgoCD. | Независимые версии плагинов. |
| **Debugging** | Логи в общем потоке. | Изолированные логи sidecar. |

## Рекомендации и лучшие практики

### Безопасность
- **Minimal Privileges:** Запускайте sidecar от непривилегированного пользователя (runAsNonRoot, runAsUser > 1000).
- **Read-Only Filesystem:** Монтируйте Tomls как read-only где возможно.
- **Network Policies:** Ограничьте сетевой доступ CMP sidecar через NetworkPolicy.
- **Image Scanning:** Сканируйте образы sidecar на уязвимости (Trivy, Snyk).
- **Secrets Management:** Не храните секреты в образах; используйте Vault, SOPS, External Secrets.

### Производительность
- **Кеширование**: Используйте локальное кеширование в sidecar для инструментов, требующих скачивания тяжелых зависимостей.
- **Размер образов**: Держите образы плагинов минимальными (на базе Distroless или Alpine) для ускорения автоскейлинга `repo-server`.
- **Resource Limits:** Устанавливайте CPU/memory limits для sidecar контейнеров.
- **Lazy Init:** Используйте init-контейнеры для тяжелых зависимостей, а не для каждого запуска.

### Надежность
- **Health Checks:** Добавляйте liveness/readiness probes для CMP sidecar.
- **Graceful Shutdown:** Корректно обрабатывайте SIGTERM для завершения текущих операций.
- **Retry Logic:** Реализуйте повторные попытки при временных ошибках (registry unavailable, network timeout).

### Устранение проблем
- **Логирование:** Включите debug-логирование для отладки discovery/generate фаз.
- **Мониторинг:** Добавьте алерты на ошибки CMP (rate > 5%).
- **Инструменты:** Используйте `argocd admin` для диагностики серверных проблем.

## Ограничения и edge cases

### Ограничения

1. **Overhead:** Каждый sidecar добавляет потребление ресурсов (CPU/memory) в под repo-server.
2. **Сложность отладки:** Мультиконтейнерные поды сложнее отлаживать.
3. **Зависимость от ArgoCD:** Версия CMP v2 привязана к версии ArgoCD.
4. **Сетевой трафик:** UNIX-сокеты работают только внутри пода; нельзя вынести CMP наружу.

### Edge Cases

1. **Конфликт плагинов:** Если два плагина подходят для одной директории, используется первый найденный.
2. **Большие репозитории:** При большом количестве файлов discovery может работать медленно.
3. **Секреты в init-контейнерах:** Init-контейнеры не имеют доступа к Kubernetes Secrets.
4. **Мультикаст:** При использовании несколько CMP sidecar могут конфликтовать за ресурсы.
5. **Образы с тегами:** Используйте immutable теги для reproducibility.
6. **Helm dependencies:** CMP не кеширует зависимости; нужно кешировать самостоятельно.
7. **Версии инструментов:** Разные плагины могут требовать разные версии одного инструмента.

## Диагностика

### Базовые команды

```bash
# Проверка pod repo-server
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-repo-server

# Логи CMP sidecar
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server -c <cmp-name>

# Проверка plugin.yaml
kubectl exec -it -n argocd deployment/argocd-repo-server -c <cmp-name> -- cat /home/argocd/cmp-server/config/plugin.yaml

# Ручное тестирование generate
kubectl exec -it -n argocd deployment/argocd-repo-server -c <cmp-name> -- /usr/local/bin/my-tool generate

# Просмотр переменных окружения
argocd app get <app-name> --plugin-env

# Проверка registration плагина
argocd admin settings repo-server list-plugins
```

### Отладка CMP

```bash
# Включить debug логирование
kubectl set env deployment/argocd-repo-server -n argocd ARGOCD_DEBUG=true

# Проверить discovery rules
kubectl exec -it -n argocd deployment/argocd-repo-server -c <cmp-name> -- \
  /usr/local/bin/argocd-cmp-server --discovery

# Просмотреть все зарегистрированные плагины
argocd admin settings repo-server list-plugins --namespace argocd
```

### См. также

- [RBAC — модель доступа](./argocd_rbac_deep.md) — Модель доступа, policy.csv, встроенные роли, JWT-токены, диагностика.
- [Безопасность](./argocd_security_hardening.md) — GPG, NetworkPolicies, mTLS, SecurityContext, proxy, audit logging.
- [Disaster Recovery](./argocd_disaster_recovery.md) — Бэкап, восстановление, etcd snapshot, HA, geo-recovery.

## Дополнительная информация

### Связанные документы

- [Обзор ArgoCD](./argocd_overview.md) — общая архитектура ArgoCD.
- [Интеграция с Vault (AVP)](./argocd_vault_integration.md) — пример CMP v2 для секретов.
- [Интеграция с Helm](./helm_integration.md) — стандартная поддержка Helm.
- [Синхронизация и политики](./synchronization.md) — Sync Waves и хуки.
- [Управление секретами (SOPS)](../../Security/Tools/sops_overview.md) — шифрование секретов.
- [Helmwave Overview](../../Kubernetes/ToolsUtilities/Helm/helmwave_overview.md) — документация Helmwave.

### Официальные ресурсы

- [ArgoCD Documentation: Config Management Plugins](https://argo-cd.readthedocs.io/en/stable/operator-manual/config-management-plugins/)
- [QBEC Documentation](https://qbec.io/)
- [Helmfile Documentation](https://helmfile.readthedocs.io/)
- [Helmwave Documentation](https://helmwave.github.io/)
- [ArgoCD Vault Plugin](https://github.com/argoproj-labs/argocd-vault-plugin)
