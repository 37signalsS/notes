# ArgoCD — расширение функционала через Custom Tooling

ArgoCD обладает встроенной поддержкой популярных инструментов (Helm, Kustomize, Jsonnet), однако для специфических задач (использование QBEC, Helmwave, Helmfile) или кастомной генерации манифестов предусмотрен механизм **Custom Tooling** на базе **Config Management Plugins (CMP)**.

## Определения

**Config Management Plugin (CMP) v2** — современная архитектура плагинов в ArgoCD (v2.4+), работающая в изолированных **sidecar-контейнерах** пода `argocd-repo-server`. Это обеспечивает безопасность и независимость зависимостей.

**Discovery (Обнаружение)** — механизм автоматического определения подходящего плагина для конкретной директории в Git на основе наличия файлов или аннотаций.

**Фаза инициализации (Init Phase)** — этап подготовки окружения (скачивание сабчартов, расшифровка секретов, запуск `npm install`).

**Фаза генерации (Generate Phase)** — выполнение команды, результатом которой должен быть поток (stream) валидных YAML-манифестов Kubernetes.

**QBEC** — инструмент на базе Jsonnet для описания объектов Kubernetes для нескольких окружений.

**git-crypt** — утилита для прозрачного шифрования файлов в Git.

## Основные концепции

### Архитектура CMP v2

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

## Дополнительная информация

### Сравнение CMP v1 и CMP v2

| Характеристика | CMP v1 (Legacy) | CMP v2 (Modern) |
| :--- | :--- | :--- |
| **Изоляция** | Отсутствует (общие зависимости). | Полная (sidecar-контейнеры). |
| **Место конфигурации** | ConfigMap `argocd-cm`. | Файл `plugin.yaml` в sidecar. |
| **Масштабируемость** | Низкая. | Высокая (независимые плагины). |
| **Безопасность** | Общие права Repo Server. | Уникальные SecurityContext и RBAC. |

### Диагностика и отладка

- **Проверка регистрации**: Если плагин не виден в UI, проверьте логи sidecar на наличие ошибок парсинга `plugin.yaml`.
- **Ручное тестирование**:
  ```bash
  kubectl exec -it deployment/argocd-repo-server -c <cmp-name> -- /usr/local/bin/my-tool generate
  ```
- **Просмотр переменных**: Используйте `argocd app get <app-name> --plugin-env`, чтобы проверить, какие переменные доходят до плагина.

### Рекомендации по производительности
- **Кеширование**: Используйте локальное кеширование в sidecar для инструментов, требующих скачивания тяжелых зависимостей.
- **Размер образов**: Держите образы плагинов минимальными (на базе Distroless или Alpine) для ускорения автоскейлинга `repo-server`.

**Связанные документы:**
- [Обзор ArgoCD](./argocd_overview.md)
- [Интеграция с Vault (AVP)](./argocd_vault_integration.md) — пример CMP v2.
- [Управление секретами (SOPS)](../../Security/Tools/sops_overview.md)

**Официальные ресурсы:**
- [ArgoCD Documentation: Config Management Plugins](https://argo-cd.readthedocs.io/en/stable/operator-manual/config-management-plugins/)
- [QBEC Documentation](https://qbec.io/)
