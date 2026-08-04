# ArgoCD: Расширение функционала через Custom Tooling

ArgoCD обладает встроенной поддержкой популярных инструментов (Helm, Kustomize, Jsonnet), однако для специфических задач (например, использование QBEC или git-crypt) предусмотрен механизм **Custom Tooling** и **Config Management Plugins (CMP)**.

## Определения

- **Config Management Plugin (CMP)** — плагин, позволяющий ArgoCD обрабатывать репозитории с помощью сторонних инструментов генерации манифестов.
- **Init Phase (Фаза инициализации)** — этап подготовки перед генерацией манифестов (скачивание зависимостей, расшифровка секретов).
- **Generate Phase (Фаза генерации)** — выполнение команды, результатом которой должен быть валидный YAML-поток (stream), применяемый в кластер.
- **QBEC** — инструмент на базе Jsonnet для описания объектов Kubernetes для нескольких окружений.
- **git-crypt** — утилита для прозрачного шифрования файлов в Git-репозитории.

## Базовые концепции

### Механизм работы кастомных инструментов

ArgoCD обрабатывает любое приложение (даже Helm) через двухфазный цикл:
1. **init**: Подготовка окружения.
2. **generate**: Получение финального YAML.

Для работы кастомных инструментов необходимо:
1. Описать плагин в конфигурации ArgoCD.
2. Обеспечить наличие необходимых бинарных файлов в поде `argocd-repo-server`.

### Методы добавления бинарных файлов

- **Custom Image (BYOI)**: Сборка собственного образа `argocd-repo-server` с предустановленными утилитами. Рекомендуется для стабильных Production-сред.
- **Init-container**: Использование `initContainers` для скачивания или копирования бинарных файлов в разделяемый том (`emptyDir`). Позволяет динамически обновлять инструменты без пересборки образа.

## Практические сценарии

### Сценарий 1: Интеграция QBEC (CMP v1)

QBEC позволяет эффективно управлять Helm-чартами через Jsonnet.

**1. Настройка плагина в `argocd-cm`:**
```yaml
data:
  configManagementPlugins: |
    - name: qbec
      generate:
        command: [sh, -xc]
        args: ['qbec show "$ENVIRONMENT" -S --force:k8s-namespace "$ARGOCD_APP_NAMESPACE"']
```

**2. Добавление бинарных файлов через Init-container:**
Отредактируйте Deployment `argocd-repo-server`:
```yaml
spec:
  template:
    spec:
      volumes:
      - name: custom-tools
        emptyDir: {}
      initContainers:
      - name: download-tools
        image: alpine:3.12
        command: [sh, -c]
        args:
        - wget -qO- https://github.com/splunk/qbec/releases/download/v0.12.2/qbec-linux-amd64.tar.gz | tar -xvzf - -C /custom-tools/
        volumeMounts:
        - name: custom-tools
          mountPath: /custom-tools
      containers:
      - name: argocd-repo-server
        volumeMounts:
        - mountPath: /usr/local/bin/qbec
          name: custom-tools
          subPath: qbec
```

### Сценарий 2: Использование git-crypt для секретов

`git-crypt` требует расшифровки репозитория на ранней стадии (при клонировании). Один из способов — использование скрипта-обертки над `git`.

**1. Скрипт-обертка для `git`:**
```bash
#!/bin/sh
# git-wrapper.sh
$(dirname $0)/git.bin "$@"
ec=$?
# Выполняем unlock только при команде fetch и наличии признаков git-crypt
[ "$1" = fetch ] && [ -d .git-crypt ] || exit $ec
GNUPGHOME=/app/config/gpg/keys git-crypt unlock 2>/dev/null
exit $ec
```

**2. Настройка GPG ключей:**
Сгенерируйте и импортируйте ключи в ArgoCD через Kubernetes Secret:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: argocd-gpg-keys-secret
  namespace: argocd
stringData:
  8CB8B24F50B4797D: |-
    -----BEGIN PGP PRIVATE KEY BLOCK-----
    ...
```

**3. Проброс ключей в `argocd-repo-server`:**
```yaml
spec:
  template:
    spec:
      volumes:
      - name: gpg-keys
        projected:
          sources:
          - secret:
              name: argocd-gpg-keys-secret
          - configMap:
              name: argocd-gpg-keys-cm
```

### Сценарий 3: Настройка объекта Application для QBEC

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
spec:
  source:
    path: examples/test-app
    plugin:
      name: qbec
      env:
        - name: ENVIRONMENT
          value: dev
    repoURL: https://github.com/example/qbec-app
```

## Дополнительная информация

### CMP v1 vs CMP v2

В современных версиях ArgoCD (v2.4+) рекомендуется использовать **CMP v2**. 

#### Ключевые отличия и заблуждения
1. **Архитектура**: В v2 каждый плагин работает в отдельном **sidecar-контейнере** пода `argocd-repo-server`. Это обеспечивает изоляцию зависимостей и безопасность.
2. **Тип ресурса**: Распространенное заблуждение, что `ConfigManagementPlugin` — это Kubernetes CRD. На самом деле это **структура данных**, описываемая в ConfigMap, которую считывает CMP-сервер внутри sidecar. Команда `kubectl get configmanagementplugin` вернет ошибку.
3. **Регистрация**: Плагин регистрируется путем монтирования файла `plugin.yaml` в директорию `/home/argocd/cmp-server/config/` внутри sidecar-контейнера.

### Сценарий 4: Интеграция Helmfile и Helmwave (CMP v2)

Для использования этих инструментов требуется сложная настройка `repo-server`.

**1. Подготовка бинарных файлов (init-container):**
Используется для загрузки инструментов в общую директорию `/helm-bin`.

**2. Настройка Sidecar-контейнеров:**
Добавляются в `extraContainers` деплоймента `argocd-repo-server`.

```yaml
# Пример фрагмента values.yaml для ArgoCD Helm Chart
repoServer:
  extraContainers:
    - name: helmfile-cmp
      command: [/var/run/argocd/argocd-cmp-server] # Точка входа для всех CMP v2
      image: alpine:3.12
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

**3. Специфика Helmwave**:
В отличие от Helmfile, **Helmwave** чувствителен к состоянию кластера (сравнивает текущее и желаемое). Это требует:
- Настройки RBAC для ArgoCD (ClusterRole/Binding), чтобы плагин мог читать ресурсы кластера.
- Соблюдения строгой идемпотентности чартов (наличие необходимых меток управления).

### Полезные команды для отладки CMP

```bash
# Перезапуск для применения изменений в ConfigMap
kubectl rollout restart deployment argocd-repo-server -n argocd

# Проверка конфигурации внутри контейнера
kubectl exec -n argocd deployment/argocd-repo-server -c <container-name> -- cat /home/argocd/cmp-server/config/plugin.yaml

# Просмотр логов конкретного плагина
kubectl logs -n argocd deployment/argocd-repo-server -c <container-name>
```

**Связанные документы:**
- [Обзор ArgoCD](./argocd_overview.md)
- [ArgoCD: Интеграция с Vault](./argocd_vault_integration.md) — пример использования CMP v2.
- **[Helmfile: декларативный оркестратор](../../Kubernetes/ToolsUtilities/Helm/helmfile_overview.md)**
- **[Helmwave: декларативный оркестратор](../../Kubernetes/ToolsUtilities/Helm/helmwave_overview.md)**
- [Управление секретами в GitOps](../secrets_encryption.md)

**Официальные ресурсы:**
- [ArgoCD: Config Management Plugins](https://argo-cd.readthedocs.io/en/stable/operator-manual/config-management-plugins/)
- [QBEC Documentation](https://qbec.io/)
