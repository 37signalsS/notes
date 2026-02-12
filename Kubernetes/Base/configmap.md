# Определения

## ConfigMap

**ConfigMap** — это объект API, который позволяет хранить неконфиденциальные конфигурационные данные в виде пар "ключ-значение". Его главная задача — **отделить конфигурацию от кода приложения**, что делает приложения переносимыми и легко настраиваемыми для разных окружений (dev, staging, prod) без пересборки Docker-образа.

Ключевое правило: Используйте ConfigMap для настроек, которые могут меняться, а [Secret](./secret.md) — для конфиденциальных данных (пароли, токены, ключи API).

# Основные концепции

## Способы создания ConfigMap

### Декларативно: из манифеста (рекомендуемый способ)

Это самый надежный и воспроизводимый подход.

```yaml
# app-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
  namespace: my-app
data:
  # Простые ключ-значение
  APP_COLOR: "blue"
  APP_MODE: "production"

  # Ключ, значением которого является целый файл
  nginx.conf: |
    server {
        listen 80;
        location / {
            root /app;
            index index.html;
        }
    }
binaryData:
  # Бинарные данные, кодированные в Base64
  logo.png: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
```

### Императивно: с помощью `kubectl`

Удобно для быстрого создания или для данных, генерируемых скриптами.

```bash
# Из файла (ключ = имя файла, значение = содержимое)
kubectl create configmap my-config-from-file --from-file=path/to/config.json

# Из нескольких файлов
kubectl create configmap my-config-from-files --from-file=path/to/config1.json --from-file=path/to/config2.xml

# Из литералов (явное указание ключ-значение)
kubectl create configmap my-config-from-literals --from-literal=KEY1=VALUE1 --from-literal=KEY2=VALUE2
```

## Способы использования ConfigMap в [подах](./pod.md)

| Способ | Типичные случаи | Обновления | Особенности |
| :--- | :--- | :--- | :--- |
| **`env`/`envFrom`** | Флаги, небольшие параметры | **Не обновляются** автоматически | Простота, но требует рестарта Pod для новых значений |
| **`volume`** | Файлы конфигурации, ключи | **Обновляются** атомарно | Гибкое монтирование, позволяет обновлять конфиг на лету |
| **`subPath`** | Монтирование одного файла в существующую директорию | **Не обновляется** автоматически | Удобно, но блокирует автоматические обновления |
| **`projected`** | Сборка конфигурации из нескольких источников | **Обновляются**, как у `volume` | Единая точка монтирования для разных ресурсов |

### Как переменные окружения (`env`, `envFrom`)

Подходит для передачи простых строковых значений в приложение.

```yaml
# ...
spec:
  containers:
    - name: my-app
      image: my-app:1.0.0
      env:
        # 1. Передать значение одного конкретного ключа
        - name: APP_COLOR_SETTING
          valueFrom:
            configMapKeyRef:
              name: app-config # Имя ConfigMap
              key: APP_COLOR    # Ключ, значение которого нужно взять
              optional: false   # Под упадет, если ConfigMap или ключ не найдены
      # 2. Передать все ключи из ConfigMap как переменные окружения
      envFrom:
        - configMapRef:
            name: app-config
            optional: true # Под запустится, даже если ConfigMap не найден
```

### Как файлы в томе (`volume`)

Это самый распространенный и мощный способ. ConfigMap монтируется как директория в файловую систему контейнера, где каждый ключ становится файлом.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: nginx-pod
spec:
  containers:
    - name: nginx
      image: nginx:1.28.0
      volumeMounts:
        - name: config-volume
          mountPath: /etc/nginx/conf.d
  volumes:
    - name: config-volume
      configMap:
        name: app-config # Имя нашего ConfigMap
        defaultMode: 0660 # Права доступа к файлам по умолчанию
        items:
          - key: nginx.conf
            path: special_nginx.conf # Монтируем ключ nginx.conf в файл special_nginx.conf
```
Использование `items` позволяет гибко настраивать путь монтирования для каждого ключа.

### Том с `subPath`

Используйте `subPath`, чтобы смонтировать только один файл из ConfigMap, не скрывая остальное содержимое целевой директории.

```yaml
# ...
volumeMounts:
  - name: config-volume
    mountPath: /etc/nginx/nginx.conf # Указываем полный путь к файлу
    subPath: nginx.conf # Имя ключа в ConfigMap
# ...
```
**Внимание:** Использование `subPath` имеет побочный эффект — **смонтированный файл перестает обновляться автоматически** при изменении ConfigMap.

### Projected том

Объединяет несколько источников в одну директорию.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-projected
spec:
  containers:
  - name: app
    image: nginx
    volumeMounts:
    - name: all-in-one
      mountPath: /etc/app
      readOnly: true
  volumes:
  - name: all-in-one
    projected:
      sources:
      - configMap:
          name: app-config
      - secret:
          name: db-creds
```
При конфликте имен файлов приоритет имеет последний источник в списке `sources`.

## Обновление ConfigMap и его влияние на поды

Классическая ситуация: вы правите ConfigMap, применяете изменения, проверяете логи — а там всё по-старому. Приложение просто не знает, что конфигурация изменилась.

Когда под стартует, он монтирует ConfigMap как volume. Kubernetes обновляет содержимое этого volume автоматически (хоть и с задержкой), однако большинство приложений:
*   Читают конфиг только один раз при запуске.
*   Не отслеживают изменения файлов в смонтированных томах.
*   Перечитывание конфигурации в рантайме требует дополнительной логики, которую необходимо реализовывать в самом приложении.

Поэтому, чтобы гарантированно применить изменения конфигурации, зачастую требуется перезапуск пода.

| Способ использования | Поведение при обновлении ConfigMap | Что нужно делать? |
| :--- | :--- | :--- |
| **Том (`volume`)** | Файлы в смонтированной директории **обновляются автоматически** (с задержкой до минуты). | Приложение должно уметь само перечитывать файлы конфигурации. В противном случае — **перезапуск пода**. |
| **Том с `subPath`** | Файл **НЕ обновляется** автоматически. | Требуется **перезапуск пода**. |
| **Переменные окружения** | Переменные окружения **НЕ обновляются** никогда. | Требуется **перезапуск пода**. |

Для принудительного перечитывания обновлённой конфигурации, когда приложение не поддерживает динамическую перезагрузку, используйте команду:
`kubectl rollout restart deployment <deployment-name>`
Эта команда инициирует обычный `Rolling Update` для Deployment'а (или StatefulSet), но без изменения версии образа, что приведёт к созданию новых подов с актуальной конфигурацией.

## Неизменяемые (Immutable) ConfigMaps

Чтобы повысить стабильность и предсказуемость, делайте ConfigMap'ы неизменяемыми (`immutable: true`), где это возможно. Это предотвращает случайные или нежелательные изменения конфигурации.

* **Преимущества:**
  * **Безопасность:** Предотвращает случайные или вредоносные изменения.
  * **Производительность:** Снижает нагрузку на `kube-apiserver` и `kubelet`, так как им больше не нужно следить за изменениями этого объекта.
  * **Предсказуемость:** Гарантирует, что для обновления конфигурации требуется полноценный `rollout` деплоймента, что делает процесс более контролируемым.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
immutable: true # Делает ConfigMap неизменяемым
data:
  LOG_LEVEL: "info"
  MAX_CONNECTIONS: "100"
```

# Практические сценарии

## Автоматический перезапуск подов при изменении ConfigMap

По умолчанию, при изменении данных в `ConfigMap`, поды, использующие его через переменные окружения или `subPath`, **не обновляются автоматически**. Это требует ручного перезапуска, например, с помощью команды `kubectl rollout restart deployment/my-deployment`.

Чтобы автоматизировать этот процесс, можно использовать "трюк" с аннотацией в шаблоне пода.

### Принцип работы

Идея состоит в том, чтобы добавить в аннотации шаблона пода (`spec.template.metadata.annotations`) хеш-сумму от данных `ConfigMap`.

1. Вычисляется хеш от содержимого `ConfigMap` (например, `sha256sum`).
2. Этот хеш добавляется как значение аннотации в `Deployment`.
3. При любом изменении в `ConfigMap` его хеш также меняется.
4. Изменение аннотации в шаблоне пода расценивается Kubernetes как изменение спецификации `Deployment`.
5. Kubernetes автоматически запускает `Rolling Update`, создавая новые поды, которые подхватывают обновленный `ConfigMap`.

Этот подход полностью автоматизирует процесс обновления конфигурации и является лучшей практикой при работе с [GitOps](../../GitOps/GitOps_overview.md) и CI/CD.

### Пример реализации (с Helm)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    metadata:
      annotations:
        # При каждом изменении ConfigMap 'my-config' будет меняться хеш,
        # что вызовет автоматический rollout для Deployment'а.
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
    spec:
      containers:
      - name: app
        image: myimage:latest
        envFrom:
        - configMapRef:
            name: my-config
```

В данном примере Helm вычисляет `sha256sum` от отрендеренного шаблона `configmap.yaml` и вставляет его в аннотацию.

### Пример с `volumeMounts` и `sha256sum`

Этот более общий пример подходит для любого Deployment, где ConfigMap монтируется как том. Здесь хеш также вычисляется с помощью шаблонизатора, но демонстрируется использование с `volumeMounts`.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    metadata:
      annotations:
        config-hash: "{{ sha256sum .Values.myConfig }}"
    spec:
      containers:
      - name: app
        image: myimage:latest
        volumeMounts:
        - name: cfg
          mountPath: /app/config
      volumes:
      - name: cfg
        configMap:
          name: my-config
```

## Дополнительная информация

## Рекомендации и лучшие практики

*   **Предпочитайте монтирование через том:** Это позволяет обновлять конфигурацию на лету (если приложение это поддерживает).
*   **Именуйте и версионируйте ConfigMap:** Давайте осмысленные имена (например, `nginx-config-v2`) для предсказуемости развертываний.
*   **Проверяйте перед применением:** Используйте `kubectl diff -f my-manifest.yaml` для просмотра изменений.
*   **Ограничение размера:** Размер одного ConfigMap не должен превышать 1 MiB.
*   **Права доступа:** Управляйте правами на смонтированные файлы через `defaultMode` в `volume` и `securityContext.fsGroup` в поде.
*   **Бинарные данные:** Для нетекстовых данных используйте поле `binaryData`.
