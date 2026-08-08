# Argo CD Image Updater — автоматизация обновления образов

**Argo CD Image Updater** — это контроллер для Argo CD, который отслеживает изменения в реестрах контейнеров (Container Registries) и автоматически обновляет версии образов в приложениях. Это позволяет реализовать цикл непрерывной доставки (CD), где публикация нового образа в реестре инициирует автоматический деплой без ручного редактирования Git-репозитория.

## Определения

- **Image Updater** — вспомогательный сервис, опрашивающий API реестров образов (Harbor, Docker Hub, AWS ECR) на наличие новых тегов.
- **Write-back Method** — механизм фиксации изменений версии образа.
    - **Git (Declarative)** — запись обновленного тега обратно в Git-репозиторий в виде коммита.
    - **API (Imperative)** — временное переопределение параметров приложения в оперативной памяти Argo CD через его API.
- **Update Strategy** — алгоритм выбора "наилучшего" тега из списка доступных в реестре.
- **Pull Secret** — секрет Kubernetes типа `docker-registry`, используемый контроллером для аутентификации в приватных реестрах.

## Базовые концепции

### Механизм работы

1. **Обнаружение:** Контроллер сканирует объекты `Application` в кластере.
2. **Фильтрация:** Выбираются только приложения, имеющие аннотацию `argocd-image-updater.argoproj.io/image-list`.
3. **Опрос реестра:** Для каждого образа выполняется запрос к API реестра. Контроллер учитывает настройки аутентификации из `argocd-image-updater-config`.
4. **Сравнение:** Найденные теги фильтруются согласно стратегии (SemVer, Latest, Name).
5. **Обновление:** Если найден тег новее текущего, инициируется запись изменений.

### Аутентификация в реестрах

Image Updater поддерживает несколько способов авторизации:

- **Секреты Kubernetes:** Указание аннотации `secret://<namespace>/<secret-name>` для конкретного образа.
- **Глобальная настройка:** Определение учетных данных в ConfigMap `argocd-image-updater-config`.
- **Cloud IAM:** Использование ролей (например, IAM Roles for Service Accounts в AWS ECR).

## Настройка и конфигурация

### Глобальные параметры (ConfigMap)

Основные настройки контроллера хранятся в `argocd-image-updater-config`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-image-updater-config
  namespace: argocd
data:
  # Интервал опроса реестров (по умолчанию 2 минуты)
  check.interval: "2m"
  # Настройка логирования
  log.level: "info"
  # Конфигурация реестров (пример для Harbor)
  registries.conf: |
    registries:
    - name: Harbor
      prefix: harbor.example.com
      api_url: https://harbor.example.com/api/v2.0
      credentials: secret://argocd/harbor-pull-secret
```

### Стратегии обновления

| Стратегия | Описание | Пример аннотации |
| :--- | :--- | :--- |
| **SemVer** | Выбор по семантическому версионированию. Поддерживает диапазоны. | `semver:~1.2` |
| **Latest** | Выбор самого последнего созданного образа (по дате). | `latest` |
| **Name** | Алфавитный порядок тегов. | `name` |
| **Digest** | Использование SHA256 хеша (для неизменяемых тегов). | `digest` |

## Практические сценарии

### Сценарий 1: Автоматизация через Git write-back (Helm)

Это рекомендуемый метод для соблюдения принципов GitOps. Контроллер создает файл `.argocd-source-<app-name>.yaml` в репозитории.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  annotations:
    # 1. Список образов и фильтр (только минорные обновления v1.x)
    argocd-image-updater.argoproj.io/image-list: app-image=my-registry/api:^1.0
    # 2. Стратегия
    argocd-image-updater.argoproj.io/app-image.update-strategy: semver
    # 3. Метод записи
    argocd-image-updater.argoproj.io/write-back-method: git
    # 4. Настройка коммита
    argocd-image-updater.argoproj.io/write-back-target: git:secret:argocd/git-creds
spec:
  source:
    helm:
      # Параметр, который будет переопределен в файле-источнике
      parameters:
      - name: image.tag
        value: 1.0.0
```

### Сценарий 2: Использование Kustomize

Для Kustomize контроллер использует механизм переопределения образов (`images` в `kustomization.yaml`).

```yaml
annotations:
  argocd-image-updater.argoproj.io/image-list: web=my-org/frontend
  argocd-image-updater.argoproj.io/web.kustomize.image-name: my-org/frontend
```

## Сравнение с Flux Image Automation

| Характеристика | Argo CD Image Updater | Flux Image Automation |
| :--- | :--- | :--- |
| **Интеграция** | Внешний аддон (Labs проект). | Встроено в ядро (Image Controller). |
| **Точность записи** | Создает отдельный YAML-файл (минимум конфликтов). | Изменяет оригинальный YAML (маркеры в комментариях). |
| **Управление** | В основном через аннотации. | Через Custom Resources (`ImagePolicy`). |
| **Масштабирование** | Привязка к объекту `Application`. | Независимые политики для всего кластера. |

## Диагностика и отладка

### Просмотр логов
Если образы не обновляются, проверьте логи контроллера:
```bash
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-image-updater
```

### Принудительное обновление
Для немедленного запуска проверки добавьте временную аннотацию:
```bash
kubectl annotate app my-app -n argocd argocd-image-updater.argoproj.io/force-update=true
```

## Дополнительная информация

**Связанные документы:**
- [Argo CD: Обзор системы](./argocd_overview.md)
- [Синхронизация в Argo CD](./synchronization.md)
- [GitOps: Образы контейнеров](../Concepts/containerization_and_image_storage.md)

**Официальные ресурсы:**
- [Документация Argo CD Image Updater](https://argocd-image-updater.readthedocs.io/)
