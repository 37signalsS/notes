# Продвинутые темы Pod в Kubernetes

## Определения

**Immutable fields** — поля спецификации пода, которые нельзя изменить после создания пода. Изменения таких полей отклоняются API-сервером.

**Fully Qualified Image Name** — полное имя образа контейнера, включающее адрес реестра, путь к репозиторию и тег (например, `docker.io/library/nginx:1.28.0`).

---

## Базовые концепции

### Редактирование работающего пода

Команда `kubectl edit pod <pod-name>` позволяет изменять только ограниченный набор полей в спецификации работающего пода. Большинство полей являются **неизменяемыми (immutable)** после создания.

**Можно редактировать:**

| Поле | Описание |
| :--- | :--- |
| `spec.containers[*].image` | Имена и теги образов для основных и init-контейнеров |
| `spec.tolerations` | Можно добавлять новые tolerations |
| `spec.activeDeadlineSeconds` | Максимальное время жизни пода |

**Нельзя редактировать (наиболее частые примеры):**

| Поле | Причина |
| :--- | :--- |
| `spec.containers` (кроме `image`) | Нельзя добавлять, удалять или изменять контейнеры, их имена, порты, переменные окружения (`env`), запросы/лимиты ресурсов, монтирование томов (`volumeMounts`) |
| `spec.volumes` | Нельзя добавлять, удалять или изменять тома |
| `metadata.name`, `metadata.namespace` | Неизменяемые идентификаторы |
| Все остальные поля спецификации | Требуется пересоздание пода |

Для внесения изменений в неизменяемые поля необходимо удалить старый под и создать новый с обновлённой конфигурацией. Эту задачу автоматизируют контроллеры более высокого уровня, такие как [Deployment](../Deployment/deployment.md).

### Полностью квалифицированные имена образов

В современных версиях Kubernetes, особенно при использовании **CRI-O**, container runtime по умолчанию может требовать указания полностью квалифицированных имён образов.

**Рекомендация:** Всегда используйте полный путь до реестра вместо коротких имён.

| Формат | Пример | Статус |
| :--- | :--- | :--- |
| Полное имя | `docker.io/library/nginx:1.28.0` | **Рекомендуется** |
| Короткое имя | `nginx` | Не рекомендуется |

**Проблема:** При указании короткого имени, которое может быть найдено в нескольких сконфигурированных реестрах, или если список реестров для поиска пуст, `kubelet` не сможет скачать образ.

**Механизм поиска:** Kubernetes ищет образ в реестрах в следующем порядке:
1. Реестры, указанные в `imagePullSecrets`
2. Реестры из конфигурации `kubelet` (параметр `--registry-burst`, `--registry-qps`)
3. Docker Hub по умолчанию (`docker.io`)

---

## Практические сценарии

### Пример 1: Обновление образа в работающем поде

```bash
# Просмотр текущего образа
kubectl get pod my-app -o jsonpath='{.spec.containers[*].image}'

# Редактирование пода (изменение image)
kubectl edit pod my-app

# В редакторе измените:
#   image: nginx:1.27
# на:
#   image: nginx:1.28

# Проверка статуса
kubectl rollout status pod my-app
```

### Пример 2: Добавление toleration к работающему поду

```bash
# Добавление toleration для запуска на узлах с taint dedicated=ml:NoSchedule
kubectl edit pod my-app

# Добавьте в spec:
spec:
  tolerations:
  - key: "dedicated"
    operator: "Equal"
    value: "ml"
    effect: "NoSchedule"
```

### Пример 3: Использование полного имени образа

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-qualified-image
spec:
  containers:
  - name: web
    # Рекомендуется: явное указание реестра и тега
    image: docker.io/library/nginx:1.28.0
    # Или для private registry:
    # image: registry.example.com/project/app:v1.2.3
```

---

## Дополнительная информация

**Связанные темы:** [Taints and Tolerations](../Scheduling/taints_and_tolerations.md), [Deployment](../Deployment/deployment.md), [Pod Image Pull Errors](../../Troubleshooting/Common_Errors/PodImagePullErrors/definitions.md), [Container Runtime](../../Concepts/control_plane_architecture.md).
