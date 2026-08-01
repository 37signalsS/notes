# Способы использования ConfigMap в подах

## Определения

**ConfigMap** — объект API Kubernetes для хранения конфигурационных данных, которые могут быть предоставлены подам (Pods) через переменные окружения, аргументы командной строки или файлы в томах. 

Использование ConfigMap позволяет реализовать принцип **Immutability** для образов контейнеров: один и тот же образ может использоваться в разных окружениях (Dev, Staging, Prod), получая специфичные настройки из внешнего ресурса.

## Основные концепции

### Механизмы доставки конфигурации

1.  **Инъекция через переменные окружения (`env`, `envFrom`):** данные считываются в момент запуска процесса. Изменение ConfigMap **не влияет** на уже запущенные контейнеры до их перезапуска.
2.  **Монтирование через тома (`volumes`):** ConfigMap подключается как директория. Файлы обновляются динамически без перезапуска подов (кроме использования `subPath`).
3.  **Использование в Sidecar-контейнерах:** с версии Kubernetes 1.29 (Native Sidecars) sidecar-контейнеры могут использовать общие тома с основным приложением для динамического обновления конфигураций (например, агенты для сбора логов или прокси-серверы).

### Сравнение способов подключения

| Способ | Обновление "на лету" | Рекомендация к использованию |
| :--- | :--- | :--- |
| **`env` / `envFrom`** | Нет | Простые флаги, лимиты, параметры логирования. |
| **`volume`** | Да (атомарно) | Сложные файлы конфигурации (nginx.conf, application.yaml). |
| **`subPath`** | Нет | Монтирование одного файла в существующую директорию. |
| **`projected`** | Да | Комбинация ConfigMap, Secret и данных API в одной папке. |

> **Технический нюанс (Hot Reload):** при использовании `volume` Kubelet обновляет файлы в контейнере через механизм символических ссылок. Это происходит атомарно. Однако приложение должно поддерживать отслеживание изменений файлов (через `inotify` или внутренние таймеры), иначе оно продолжит использовать старые данные до перезапуска.

## Практические сценарии

### Переменные окружения и отказоустойчивость

Для предотвращения ошибки `CreateContainerConfigError` при отсутствии ConfigMap используйте поле `optional`.

```yaml
spec:
  containers:
    - name: backend
      image: backend:2.1.0
      env:
        # Использование конкретного ключа
        - name: DB_TIMEOUT
          valueFrom:
            configMapKeyRef:
              name: app-config
              key: db_timeout
              optional: true # Контейнер запустится, даже если ConfigMap или ключ отсутствует
      # Импорт всех ключей как переменных
      envFrom:
        - configMapRef:
            name: global-settings
```

### Монтирование томов и управление правами

При монтировании можно управлять именами файлов и их правами доступа (Permissions). По умолчанию файлы принадлежат пользователю `root` и имеют права `0644`.

```yaml
spec:
  containers:
    - name: web-server
      image: nginx:1.27
      volumeMounts:
        - name: config-vol
          mountPath: /etc/nginx/conf.d
          readOnly: true # Рекомендуется для безопасности
  volumes:
    - name: config-vol
      configMap:
        name: web-config
        defaultMode: 0440 # Октальное представление прав (read-only для владельца и группы)
        items:
          - key: "nginx-vhost.conf"
            path: "default.conf" # Переименование файла при монтировании
            mode: 0644           # Специфичные права для конкретного файла
```

### Проблема subPath и ее решение

Использование `subPath` удобно для вставки файла в существующую директорию (например, `/etc/ssh/`), но оно блокирует автоматическое обновление файлов.

**Варианты решения:**
1.  Использовать монтирование всей директории (если возможно).
2.  Использовать `configMapGenerator` в Kustomize для генерации новых имен ConfigMap, что вызовет Rolling Update всего пода. Подробнее в [Создание ConfigMap](./creation.md).

### Использование в Sidecar-контейнерах (K8s 1.29+)

Native Sidecars позволяют гарантировать, что конфигурационный агент (например, `git-sync`) будет готов до старта основного приложения.

```yaml
spec:
  initContainers:
    - name: config-sync
      image: k8s.gcr.io/git-sync:v4.2.0
      restartPolicy: Always # Делает init-контейнер sidecar-ом
      volumeMounts:
        - name: shared-config
          mountPath: /tmp/git
  containers:
    - name: app
      image: my-app:latest
      volumeMounts:
        - name: shared-config
          mountPath: /etc/app/config
  volumes:
    - name: shared-config
      emptyDir: {}
```

### Приоритеты и переопределение переменных

Если переменная с одним и тем же именем определена и в `envFrom`, и в `env`, то значение из секции `env` (через `valueFrom` или прямое `value`) имеет **приоритет** и переопределяет значение из `envFrom`.

**Пример переопределения:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: env-override-demo
spec:
  containers:
    - name: sample
      image: busybox
      command: [ "/bin/sh", "-c", "env | grep K8S" ]
      # 1. Загружаем все ключи из ConfigMap
      envFrom:
        - configMapRef:
            name: app-config # содержит K8S_FOO: "original", K8S_BAR: "value-bar"
      # 2. Переопределяем конкретный ключ
      env:
        - name: K8S_FOO
          valueFrom:
            configMapKeyRef:
              name: app-config
              key: K8S_BAR # Теперь K8S_FOO будет равен значению K8S_BAR ("value-bar")
  restartPolicy: Never
```

В данном примере в логах пода мы увидим, что `K8S_FOO` равен значению `K8S_BAR`, так как секция `env` переопределила данные из `envFrom`.

## Дополнительная информация

### Рекомендации по безопасности и эксплуатации

*   **ReadOnly:** Всегда устанавливайте `readOnly: true` для `volumeMounts`, чтобы процесс в контейнере не мог изменить конфигурацию локально (эти изменения все равно не сохранятся в ConfigMap, но могут привести к непредсказуемому поведению).
*   **Immutable ConfigMaps:** Для стабильных конфигураций используйте `immutable: true`. Это отключает механизм `watch` со стороны Kubelet, существенно снижая нагрузку на Control Plane в больших кластерах. Подробнее в [Неизменяемые ConfigMap](./immutable.md).
*   **Автоматизация рестартов:** При изменении ConfigMap, подключенного через `env`, используйте аннотации с хешем конфига в Deployment для автоматического перезапуска подов. Подробнее в [Обновление и Rollout](./update_and_rollout.md).

**См. также:**

* [Создание ConfigMap](./creation.md) — декларативный и генеративный подходы.
* [Обновление и Rollout](./update_and_rollout.md) — стратегии перезапуска при изменении настроек.
* [Неизменяемые ConfigMap](./immutable.md) — оптимизация и безопасность.
* [Projected Volume в Pod Volumes](../Pod/volume_types/projected_volumes.md) — детальное описание агрегации данных.
