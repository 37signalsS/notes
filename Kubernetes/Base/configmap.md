# ConfigMap в Kubernetes

**Актуально для:** Kubernetes 1.30–1.32+

## Определения

*   **ConfigMap** — базовый объект API Kubernetes (группа API `core/v1`), предназначенный для хранения неконфиденциальных данных конфигурации в формате пар «ключ-значение». Позволяет отделить конфигурацию приложения от исполняемого кода и артефактов контейнера (**Separation of Concerns**), обеспечивая переносимость (Portability) образов между различными средами (dev, staging, production) без их пересборки.
*   **Словарь `data`** — поле спецификации ConfigMap для хранения строковых данных в обязательной кодировке **UTF-8**. Ключи словаря должны состоять из буквенно-цифровых символов, дефисов (`-`), знаков подчеркивания (`_`) и точек (`.`).
*   **Словарь `binaryData`** — поле спецификации ConfigMap для хранения бинарных данных произвольного формата, сериализованных в виде строк **Base64**. Используется для нетекстовых файлов (бинарные плагины, архивы, иконки, открытые TLS-сертификаты).
*   **Атомарная замена символических ссылок (Atomic Symlink Swap)** — низкоуровневый механизм подсистемы Volume Manager в `kubelet`, при котором файлы смонтированного тома ConfigMap обновляются путем создания нового каталога с таймштампом и мгновенной подмены символической ссылки `..data` через системный вызов ядра Linux `renameat()`. Исключает состояние частичного чтения (torn read) приложением.
*   **Горячая перезагрузка (Hot Reload)** — обновление конфигурации запущенного приложения без перезапуска контейнера (PID 1). Реализуется через подписку на события ядра Linux (`inotify`), опрос файлов конфигурации (polling) или отправку внешнего POSIX-сигнала (например, `SIGHUP`).
*   **Неизменяемый ConfigMap (Immutable ConfigMap)** — объект ConfigMap со свойством `immutable: true` (статус GA с версии 1.21), защищающий ресурс от модификации и снимающий нагрузку с `kube-apiserver` за счет отключения долговременных подписок (Watch) со стороны демонов `kubelet`.
*   **subPath-монтирование** — способ внедрения одиночного файла или каталога из ConfigMap в существующую директорию файловой системы контейнера без ее полного перезаписывания. Реализуется через Linux bind-mount конкретного inode файла, что полностью блокирует последующее автоматическое обновление данных в контейнере при изменении ConfigMap.

> [!IMPORTANT]
> ConfigMap не обеспечивает шифрования данных и не предназначен для хранения конфиденциальной информации (паролей, токенов, закрытых ключей). Для таких сценариев следует использовать [Secret](./secrets/secrets_basics.md).

---

## Архитектура и принципы работы

### Хранение в etcd и жесткие лимиты

ConfigMap сохраняется в распределенной базе данных `etcd` в пространстве ключей `/registry/configmaps/<namespace>/<name>`.

*   **Лимит размера в 1 MiB:** Размер объекта ConfigMap (включая имя, метки, аннотации и полезную нагрузку в полях `data` и `binaryData`) строго ограничен **1 MiB** (1 048 576 байт). Это ограничение диктуется максимальным размером запроса в `etcd` (`--max-request-bytes=1.5MB`) и накладными расходами Raft-консенсуса.
*   Попытка применить манифест, превышающий 1 MiB, отклоняется `kube-apiserver` на этапе проверки с ошибкой HTTP 413:
    ```text
    Error from server (RequestEntityTooLarge): error when creating "config.yaml":
    ConfigMap "large-config" is invalid: []: Too long: must have at most 1048576 bytes
    ```
*   Для конфигураций и артефактов размером более 1 MiB применяются `PersistentVolume`, внешние файловые хранилища или скачивание данных через Init-контейнеры. Подробнее см. [Работа с большими конфигурациями](./ConfigMap/large_configs.md).

### Пассивный жизненный цикл (отсутствие контроллера)

ConfigMap является пассивным ресурсом данных:
*   В составе `kube-controller-manager` **нет контроллера**, отслеживающего изменения ConfigMap для автоматического перезапуска рабочих нагрузок.
*   При изменении объекта ConfigMap контроллеры `Deployment`, `DaemonSet` или `StatefulSet` не получают сигналов к пересозданию подов, так как спецификация шаблона пода (`spec.template`) остается неизменной.
*   Автоматизация перезапуска реализуется на уровне CI/CD, GitOps-инструментов (Argo CD, Kustomize), хеширования аннотаций шаблона пода либо специализированных операторов (например, Stakater Reloader).

```
+------------------+         kubectl apply         +------------------+
|  Администратор / | ----------------------------> |  kube-apiserver  |
|      CI/CD       |                               +--------+---------+
+------------------+                                        | запись в etcd
                                                            v
+------------------+     Watch / Periodic Sync     +------------------+
|   Kubelet Node   | <---------------------------- |       etcd       |
|  Volume Manager  |                               +------------------+
+--------+---------+
         |
         | tmpfs + Symlink Swap
         v
+---------------------------------------------------------------------+
| Pod: Container Filesystem                                           |
| /etc/app/config/ -> ..data/ -> ..2026_10_17_18_00_00/app.yaml       |
+---------------------------------------------------------------------+
```

### Способы передачи данных в контейнеры

Kubernetes предоставляет три основных механизма передачи данных из ConfigMap в контейнеры:

| Механизм | Синтаксис манифеста | Поведение при обновлении ConfigMap | Когда применять |
| :--- | :--- | :--- | :--- |
| **Переменные окружения** | `env` / `envFrom` | **Не обновляются** без перезапуска процесса/пода. Значения считываются ядром Linux только в момент вызова `execve()` при старте контейнера. | Скалярные флаги, порты, режимы работы, переменные runtime. |
| **Монтирование тома (Каталог)** | `volumes.configMap` + `volumeMounts` | **Обновляются автоматически** Kubelet без рестарта пода (задержка от десятков секунд до 1–2 минут). | Файлы конфигурации (YAML, JSON, INI, conf), поддерживающие Hot Reload. |
| **Монтирование файла (`subPath`)** | `volumeMounts.subPath` | **Не обновляются.** Файл привязывается к inode на момент запуска контейнера. | Подмена одиночного файла в существующей директории (например, в `/etc/nginx/conf.d/`). |

### Механизм атомарной замены символических ссылок (Atomic Symlink Swap)

Когда ConfigMap монтируется как том (`volumeMounts`), демон `kubelet` проецирует данные в локальную файловую систему узла (смонтированную как `tmpfs`) в каталоге пода:
`/var/lib/kubelet/pods/<pod-uid>/volumes/kubernetes.io~configmap/<volume-name>/`

Внутри каталога выстраивается трехуровневая структура символических ссылок:

```text
/etc/config/
├── ..2026_10_17_18_00_00.123456789/      # Теневой каталог версии 1
│   ├── app.yaml
│   └── database.properties
├── ..2026_10_17_18_30_00.987654321/      # Теневой каталог версии 2 (после обновления)
├── ..data -> ..2026_10_17_18_30_00.987654321  # Атомарный симлинк
├── ..data_tmp -> ..2026_10_17_18_30_00.987654321
├── app.yaml -> ..data/app.yaml           # Файловые симлинки на ..data
└── database.properties -> ..data/database.properties
```

**Процесс обновления:**
1. Kubelet фиксирует изменение ConfigMap через Watch или плановый опрос.
2. Создается новый скрытый каталог с уникальным таймштампом `..YYYY_MM_DD_HH_MM_SS.NNNNNNNNN`.
3. В новый каталог записываются обновленные файлы из ConfigMap.
4. Создается временная символическая ссылка `..data_tmp`, указывающая на новый каталог.
5. Выполняется системный вызов ядра Linux `renameat(..data_tmp, ..data)`. Этот вызов атомарен в POSIX-совместимых файловых системах: процесс в контейнере никогда не увидит полузаписанный файл.
6. Старый теневой каталог удаляется.

**Почему `subPath` блокирует обновление:**
При использовании `subPath` ядро Linux выполняет bind-mount конкретного inode файла непосредственно в целевую точку внутри контейнера. Когда `kubelet` заменяет симлинк `..data` на уровне родительского каталога тома, inode смонтированного файла внутри контейнера остается неизменным. Файл внутри контейнера продолжит указывать на старое содержимое вплоть до полного пересоздания пода.

### Периодичность обновления Kubelet

Задержка распространения изменений из `etcd` в смонтированный том пода определяется следующими факторами:
*   Режимом кэширования `kubelet` (настройка `--config-map-mode` в kubelet config: `Watch`, `Cache` или `Quenching`). По умолчанию используется `Watch`.
*   Периодом опроса Volume Manager (`--sync-frequency`, по умолчанию 1 минута).
*   Временем кэширования локального TTL-кэша Kubelet.
В среднем на узлах под управлением Linux задержка появления новых файлов составляет **от 30 до 90 секунд**.

### Безопасность и NodeRestriction

Контроллер допуска **NodeRestriction** на стороне `kube-apiserver` строго ограничивает полномочия сервисного аккаунта Kubelet на чтение объектов ConfigMap:
*   `kubelet` конкретного узла имеет право получать (`Get`) только те объекты ConfigMap, которые привязаны к подам, непосредственно запланированным (`scheduled`) на данный узел.
*   Это минимизирует радиус поражения (Blast Radius): компрометация рабочего узла не дает злоумышленнику возможности выгрузить конфигурационные карты всего кластера.

### Неизменяемые (Immutable) ConfigMap

Начиная с Kubernetes 1.21 (GA), спецификация ConfigMap поддерживает поле `immutable: true`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: immutable-app-config
immutable: true
data:
  config.json: |
    {"env": "production", "cache_ttl": 300}
```

**Инженерные преимущества:**
1.  **Снижение нагрузки на Control Plane:** `kubelet` не устанавливает долговременные подписки (Watch) и не опрашивает API-сервер для неизменяемых объектов. В кластерах на сотни и тысячи узлов это кардинально разгружает сеть и CPU `kube-apiserver` и `etcd`.
2.  **Защита от дрейфа конфигурации (Drift Prevention):** После создания объект защищен от случайного изменения операторами или некорректными скриптами через `kubectl edit` / `kubectl apply`. Любая попытка мутации полей `data` или `binaryData` отклоняется API-сервером:
    ```text
    The ConfigMap "immutable-app-config" is invalid: data: Forbidden: field is immutable when `immutable` is set
    ```
3.  **Откат и аудит:** Обновление конфигурации выполняется исключительно путем создания нового объекта с уникальным именем (например, с хеш-суффиксом) и изменением ссылки в манифесте Deployment. Это обеспечивает детерминированный откат (Rollback).

Подробнее см. [Неизменяемые ConfigMap](./ConfigMap/immutable.md).

---

## Практические сценарии и конфигурация

### Базовый сквозной сценарий: одновременное потребление через env и том

Ниже приведен production-ready сценарий: ConfigMap предоставляет строковые параметры окружения и полноценный конфигурационный файл для демона NGINX.

#### 1. Манифест ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: web-app-config
  namespace: production
  labels:
    app.kubernetes.io/name: web-app
    app.kubernetes.io/part-of: core-services
data:
  # Простые скалярные переменные
  HTTP_PORT: "8080"
  LOG_LEVEL: "warn"
  ENABLE_METRICS: "true"
  
  # Многострочный файл конфигурации
  nginx.conf: |
    events { worker_connections 1024; }
    http {
      server {
        listen 8080;
        location /healthz {
          return 200 'OK';
          add_header Content-Type text/plain;
        }
        location / {
          root /usr/share/nginx/html;
          index index.html;
        }
      }
    }
```

#### 2. Манифест Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-app
  namespace: production
  labels:
    app.kubernetes.io/name: web-app
spec:
  replicas: 2
  selector:
    matchLabels:
      app: web-app
  template:
    metadata:
      labels:
        app: web-app
    spec:
      containers:
      - name: nginx
        image: nginx:1.27-alpine
        ports:
        - containerPort: 8080
          name: http
        
        # Способ 1: Чтение одиночной переменной через configMapKeyRef
        env:
        - name: SERVER_PORT
          valueFrom:
            configMapKeyRef:
              name: web-app-config
              key: HTTP_PORT
              optional: false
              
        # Способ 2: Массовый импорт с префиксом через envFrom
        envFrom:
        - prefix: APP_CONFIG_
          configMapRef:
            name: web-app-config
            optional: false
            
        # Способ 3: Монтирование файла конфигурации
        volumeMounts:
        - name: config-volume
          mountPath: /etc/nginx/nginx.conf
          subPath: nginx.conf   # Подменяем только один файл в /etc/nginx/
          readOnly: true
          
      volumes:
      - name: config-volume
        configMap:
          name: web-app-config
          defaultMode: 0444    # Только для чтения (восьмеричная система)
          items:
          - key: nginx.conf
            path: nginx.conf
```

#### 3. Применение и валидация

```bash
# Применение манифестов
kubectl apply -f configmap.yaml -f deployment.yaml

# Проверка статуса запуска подов
kubectl get pods -n production -l app=web-app
# → NAME                       READY   STATUS    RESTARTS   AGE
# → web-app-7b8f9d6c4-abc12    1/1     Running   0          25s
# → web-app-7b8f9d6c4-def34    1/1     Running   0          25s

# Проверка переданных переменных окружения внутри контейнера
kubectl exec -n production deploy/web-app -c nginx -- env | grep -E "SERVER_PORT|APP_CONFIG_"
# → SERVER_PORT=8080
# → APP_CONFIG_ENABLE_METRICS=true
# → APP_CONFIG_HTTP_PORT=8080
# → APP_CONFIG_LOG_LEVEL=warn

# Проверка содержимого смонтированного файла
kubectl exec -n production deploy/web-app -c nginx -- head -n 4 /etc/nginx/nginx.conf
# → events { worker_connections 1024; }
# → http {
# →   server {
# →     listen 8080;
```

---

### Монтирование каталога целиком для поддержки Hot Reload

Для обеспечения автоматического обновления конфигураций приложением без рестарта пода монтируйте том как **целостный каталог**, избегая `subPath`:

```yaml
spec:
  containers:
  - name: application
    image: custom-app:2.1.0
    volumeMounts:
    - name: dynamic-configs
      mountPath: /app/configs
      readOnly: true
  volumes:
  - name: dynamic-configs
    configMap:
      name: app-dynamic-settings
      defaultMode: 0440
```

Когда приложение подписано на события каталога `/app/configs` через API `inotify` ядра Linux, оно получает уведомление при смене симлинка `..data` и перечитывает конфигурацию на лету.

---

### Проекция данных: объединение ConfigMap, Secret и Downward API

С помощью механизма **Projected Volumes** администратор может собрать в единую директорию разнородные источники конфигурации (неконфиденциальные файлы, секреты и метаданные пода):

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: multi-config-pod
  namespace: default
spec:
  containers:
  - name: service
    image: debian:bookworm-slim
    command: ["sleep", "3600"]
    volumeMounts:
    - name: all-configs
      mountPath: /etc/service/runtime
      readOnly: true
  volumes:
  - name: all-configs
    projected:
      defaultMode: 0400
      sources:
      # Источник 1: общая конфигурация
      - configMap:
          name: global-config
          items:
          - key: settings.ini
            path: settings.ini
      # Источник 2: токен аутентификации из Secret
      - secret:
          name: auth-token-secret
          items:
          - key: api.token
            path: tokens/api.token
      # Источник 3: метаданные пода из Downward API
      - downwardAPI:
          items:
          - path: pod_info.txt
            fieldRef:
              fieldPath: metadata.name
```

Внутри `/etc/service/runtime` файлы будут доступны одновременно:
```bash
kubectl exec multi-config-pod -- ls -la /etc/service/runtime
# → drwxr-xr-x 3 root root 4096 Oct 17 18:10 .
# → lrwxrwxrwx 1 root root   12 Oct 17 18:10 ..data -> ..2026_10_17_18_10_00
# → lrwxrwxrwx 1 root root   20 Oct 17 18:10 pod_info.txt -> ..data/pod_info.txt
# → lrwxrwxrwx 1 root root   20 Oct 17 18:10 settings.ini -> ..data/settings.ini
# → drwxr-xr-x 2 root root 4096 Oct 17 18:10 tokens
```
Подробнее см. [Projected Volumes](./Pod/volume_types/projected_volumes.md).

---

### Стратегии обновления и перезапуска зависимых подов

Поскольку ConfigMap не вызывает перезапуск подов автоматически, в production-окружениях используются три основных SRE/DevOps паттерна:

#### Паттерн 1: Внедрение контрольной суммы (Config Checksum Annotation)

Штатный паттерн в Helm-чартах и CI/CD пайплайнах. В шаблон пода внедряется аннотация с SHA-256 хешем содержимого ConfigMap:

```yaml
spec:
  template:
    metadata:
      annotations:
        # При изменении содержимого ConfigMap хеш меняется, порождая новую ревизию ReplicaSet
        checksum/config: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    spec:
      containers:
      - name: backend
        image: backend:v1.2.0
```

#### Паттерн 2: Kustomize с `configMapGenerator` (Content-Hash Naming)

Инструмент Kustomize генерирует имя ConfigMap с суффиксом на основе хеша содержимого:

```yaml
# kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
configMapGenerator:
- name: service-config
  files:
  - configs/app.properties
```

При сборке создается объект с именем `service-config-f7m8k9g6`, и Kustomize автоматически обновляет ссылку на это имя в спецификации `Deployment`. Контроллер Deployment видит изменение шаблона пода и инициирует стандартный Rolling Update без простоя сервиса.

#### Паттерн 3: Ручной перезапуск через CLI

Если изменение внесено в существующий ConfigMap без хеширования, системный администратор выполняет принудительный плавный перезапуск контроллера:

```bash
kubectl rollout restart deployment/web-app -n production
# → deployment.apps/web-app restarted

# Контроль процесса раскатки
kubectl rollout status deployment/web-app -n production
# → Waiting for deployment "web-app" rollout to finish: 1 out of 2 new replicas have been updated...
# → deployment "web-app" successfully rolled out
```

#### Паттерн 4: Hot Reload через SIGHUP-триггер или Sidecar

Для сервисов вроде Prometheus, NGINX или Fluentd, умеющих перечитывать конфиг по сигналу или HTTP-вызову, в под добавляется sidecar-контейнер (например, `configmap-reload`), который следит за файлом и вызывает локальный эндпоинт:

```bash
# Ручная отправка сигнала перезагрузки процессу в контейнере
kubectl exec -n production deploy/web-app -c nginx -- nginx -s reload
# → 2026/10/17 18:15:00 [notice] 1#1: signal 1 (SIGHUP) received, reloading configuration
```

Подробнее все стратегии разобраны в [Обновление и плавный перезапуск](./ConfigMap/update_and_rollout.md).

---

### Работа с бинарными данными (`binaryData`)

Поле `binaryData` используется для хранения двоичных файлов (например, сжатых архивов gzip, скомпилированных WASM-модулей, Java-хранилищ ключей JKS). Значения должны быть закодированы в Base64.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: binary-assets
  namespace: default
binaryData:
  # Base64-представление сжатого архива gzip
  app-assets.tar.gz: "H4sICB2XomYCA2Fzc2V0cy50YXIA7P1pc9tGkigcv/pTzDx2A..."
```

При императивном создании из файла утилита `kubectl` автоматически распознает бинарный контент и размещает его в секцию `binaryData`:

```bash
kubectl create configmap binary-assets --from-file=app-assets.tar.gz --dry-run=client -o yaml
```

---

## Операции и команды

Сводка типовых команд системного администратора и инженера SRE для управления и аудита ConfigMap:

### Создание и генерация манифестов

```bash
# 1. Создание из литералов (ключ=значение)
kubectl create configmap app-env \
  --from-literal=ENVIRONMENT=production \
  --from-literal=DB_TIMEOUT=30s \
  --namespace=default
# → configmap/app-env created

# 2. Создание из файла (имя файла становится ключом)
kubectl create configmap app-file-cfg \
  --from-file=/etc/configs/app.conf \
  --namespace=default
# → configmap/app-file-cfg created

# 3. Создание с явным указанием имени ключа для файла
kubectl create configmap app-custom-key \
  --from-file=custom_name.json=/etc/configs/raw.json \
  --namespace=default
# → configmap/app-custom-key created

# 4. Создание из каталога (каждый файл внутри становится ключом)
kubectl create configmap app-dir-cfg \
  --from-file=/etc/configs/ \
  --namespace=default
# → configmap/app-dir-cfg created

# 5. Создание из .env-файла (формат KEY=VALUE на каждой строке)
kubectl create configmap app-dotenv \
  --from-env-file=.env \
  --namespace=default
# → configmap/app-dotenv created

# 6. Декларативная генерация манифеста (Dry-Run без применения в кластер)
kubectl create configmap app-cfg \
  --from-file=app.yaml \
  --dry-run=client -o yaml > configmap.yaml
```

### Инспекция и чтение данных

```bash
# Просмотр списка ConfigMap в namespace с количеством ключей и возрастом
kubectl get configmap -n production
# → NAME             DATA   AGE
# → kube-root-ca.crt 1      45d
# → web-app-config   4      2h

# Получение детальной информации о ресурсе и его ключах
kubectl describe configmap web-app-config -n production
# → Name:         web-app-config
# → Namespace:    production
# → Labels:       app.kubernetes.io/name=web-app
# → Data
# → ====
# → HTTP_PORT:
# → ----
# → 8080
# → LOG_LEVEL:
# → ----
# → warn

# Извлечение содержимого конкретного ключа через jsonpath
kubectl get configmap web-app-config -n production \
  -o jsonpath='{.data.nginx\.conf}'
# → events { worker_connections 1024; }
# → http { ... }

# Расчет суммарного объема данных объекта ConfigMap в байтах
kubectl get configmap web-app-config -n production -o json | \
  jq '[.data // {}, .binaryData // {} | to_entries[] | .value | length] | add'
# → 284
```

### Редактирование и аудит зависимостей

```bash
# Интерактивное редактирование ConfigMap в кластере
kubectl edit configmap web-app-config -n production

# Патчинг отдельного ключа на лету
kubectl patch configmap web-app-config -n production \
  --type merge \
  -p '{"data":{"LOG_LEVEL":"debug"}}'
# → configmap/web-app-config patched

# Поиск всех подов в namespace, использующих данный ConfigMap (через volumes или env)
kubectl get pods -n production -o json | jq -r --arg CM "web-app-config" '
  .items[] | 
  select(
    (.spec.volumes[]?.configMap.name == $CM) or 
    (.spec.containers[].env[]?.valueFrom.configMapKeyRef.name == $CM) or
    (.spec.containers[].envFrom[]?.configMapRef.name == $CM)
  ) | .metadata.name'
# → web-app-7b8f9d6c4-abc12
# → web-app-7b8f9d6c4-def34
```

---

## Диагностика и устранение неисправностей

### Матрица типовых ошибок

| Ошибка / Симптом | Первопричина | Способ диагностики | Решение |
| :--- | :--- | :--- | :--- |
| `CreateContainerConfigError` | В манифесте пода указан несуществующий ConfigMap или отсутствующий ключ при `optional: false` | `kubectl describe pod <name>` (блок Events) | Проверить наличие объекта: `kubectl get cm <name>`. Создать недостающий объект/ключ либо указать `optional: true`, если параметр не является обязательным. |
| `FailedMount` (Warning в событиях) | Ошибка монтирования тома: ConfigMap не найден в том же Namespace, либо опечатка в имени | `kubectl get events --field-selector reason=FailedMount` | Убедиться, что ConfigMap и Pod находятся в одном Namespace. Проверить регистр букв в имени. |
| Файл в контейнере не обновился после изменения ConfigMap | Использован механизм `subPath` (bind-mount), либо приложение кэширует конфигурацию в RAM | Проверить манифест: `grep -A 5 subPath deployment.yaml` | 1. Использовать монтирование директории целиком.<br>2. Выполнить `kubectl rollout restart deployment/<name>`. |
| Переменные окружения (`env`) содержат старые значения | Переменные окружения фиксируются при старте процесса в ядре Linux и не меняются в runtime | Сверить `kubectl exec <pod> -- env` с содержимым ConfigMap | Выполнить `kubectl rollout restart deployment/<name>`, чтобы пересоздать поды с новыми переменными. |
| Ошибка `RequestEntityTooLarge` (HTTP 413) | Суммарный размер ConfigMap превышает жесткий лимит etcd в 1 MiB | Текст ошибки при `kubectl apply` | Разделить ConfigMap на несколько объектов, сжать данные (`binaryData` gzip) или вынести артефакты в `PersistentVolume` / S3. |
| Ошибка доступа `Permission Denied` внутри контейнера | Процесс в контейнере работает под непривилегированным пользователем (UID != 0), а `defaultMode` запрещает чтение | `kubectl logs <pod>`, проверка прав `ls -l` в контейнере | Настроить поле `defaultMode: 0444` (чтение для всех) или настроить `fsGroup` в `pod.spec.securityContext`. |
| Ошибка парсинга YAML (`found character that cannot start any token`) | В значениях ключей ConfigMap использованы знаки табуляции (`\t`) вместо пробелов или нарушена вложенность | Валидатор YAML (yamllint) или `kubectl apply --dry-run=client` | Заменить все табуляции на пробелы, экранировать спецсимволы или использовать блок-литерал `\|`. |

### Диагностика на уровне рабочего узла (Sysadmin / Bare-Metal)

Если прикладные утилиты не дают полной картины, системный администратор выполняет прямую диагностику на узле:

```bash
# 1. Поиск UID проблемного пода
POD_UID=$(kubectl get pod web-app-7b8f9d6c4-abc12 -n production -o jsonpath='{.metadata.uid}')

# 2. Переход на узел, где запущен под, и инспекция смонтированного тома Kubelet
cd /var/lib/kubelet/pods/${POD_UID}/volumes/kubernetes.io~configmap/config-volume/

# 3. Проверка цепочки символических ссылок
ls -la
# → lrwxrwxrwx 1 root root ..data -> ..2026_10_17_18_20_00.123456789
# → lrwxrwxrwx 1 root root nginx.conf -> ..data/nginx.conf
# → drwxr-xr-x 2 root root ..2026_10_17_18_20_00.123456789

# 4. Просмотр системных логов Kubelet на предмет ошибок монтирования
journalctl -u kubelet -e --no-pager | grep -E "config-volume|FailedMount"
```

---

## Лучшие практики

### Архитектура и надежность

1.  **Строгий запрет секретов:** Никогда не сохраняйте в ConfigMap токены доступа, пароли, приватные ключи, токены баз данных или учетные записи сервисов. Для таких данных применяйте [Secret](./secrets/secrets_basics.md) или внешние провайдеры (HashiCorp Vault, External Secrets Operator).
2.  **Иммутабельность в GitOps-пайплайнах:** В production-средах используйте генерацию уникальных имен объектов на основе хеша содержимого (`configMapGenerator` в Kustomize или хеш в Helm) либо включайте флаг `immutable: true`. Это гарантирует детерминированное развертывание и исключает рассинхронизацию реплик (Config Skew Window).
3.  **Принцип Fail-Fast (`optional: false`):** Для критичных конфигураций приложения всегда устанавливайте `optional: false` (значение по умолчанию). Под должен аварийно завершаться на этапе инициализации с ошибкой `CreateContainerConfigError`, если обязательный конфигурационный файл отсутствует, не допуская старта приложения с некорректными дефолтными параметрами.
4.  **Отказ от `subPath` при необходимости динамических обновлений:** Если приложение должно подхватывать конфигурацию без перезапуска пода, монтируйте ConfigMap исключительно как директорию.

### Безопасность

1.  **Принцип наименьших привилегий для файлов (`defaultMode`):** Явно задавайте режим доступа к смонтированным файлам тома. Для файлов, требующих только чтения непривилегированным пользователем контейнера, указывайте `defaultMode: 0440` или `0444`.
    > [!WARNING]
    > В YAML восьмеричные числа должны начинаться с `0`. Значение `defaultMode: 0644` в YAML интерпретируется корректно, однако запись без ведущего нуля (`644`) будет прочитана как десятичное число (что соответствует правам `01204` с установленным битом sticky/SGID).
2.  **Ограничение RBAC:** Запрещайте права на запись (`create`, `update`, `patch`, `delete`) для ресурса `configmaps` сервисным аккаунтам (`ServiceAccount`) прикладных приложений в пространстве имен. Приложения должны быть потребителями конфигурации, а не ее авторами.
3.  **Активация NodeRestriction:** Убедитесь, что в Control Plane кластера включен admission-плагин `NodeRestriction`, исключающий доступ Kubelet к чужим ConfigMap.

### Производительность и масштабируемость

1.  **Контроль размера полезной нагрузки:** Держите размер ConfigMap в пределах до 50–100 КиБ. Хранение сотен крупных объектов с частыми изменениями приводит к деградации производительности `etcd` и повышенному потреблению CPU демоном `kube-apiserver`.
2.  **Отключение Watch через `immutable: true`:** Для статических конфигураций базовой инфраструктуры (coredns, ingress-controllers, mesh-конфиги), тиражируемых на сотни узлов, объявляйте ConfigMap неизменяемым. Это освобождает тысячи постоянных HTTP/2 stream-соединений между узлами и Control Plane.

---

## Дополнительная информация

### Детальные руководства по ConfigMap

*   **[Создание ConfigMap](./ConfigMap/creation.md)** — подробные декларативные, генеративные (Kustomize, Helm) и императивные методы формирования объектов.
*   **[Использование в подах](./ConfigMap/pod_usage.md)** — расширенные сценарии монтирования, маппинг ключей (`items`), права доступа и переменные `envFrom`.
*   **[Обновление и плавный перезапуск](./ConfigMap/update_and_rollout.md)** — архитектура Kubelet Volume Manager, Hot Reload, стратегии Rollout Restart и хеширование.
*   **[Неизменяемые ConfigMap](./ConfigMap/immutable.md)** — глубокий разбор флага `immutable: true`, тесты производительности и паттерны ротации.
*   **[Работа с большими конфигурациями](./ConfigMap/large_configs.md)** — стратегии обхода лимита 1 MiB в etcd: сжатие, Projected Volumes, Init-контейнеры, PV.
*   **[Практические шаблоны](./ConfigMap/practical_templates.md)** — готовые манифесты для NGINX, HAProxy, Prometheus, микросервисов и многоконтурных сред.
*   **[Лучшие практики](./ConfigMap/best_practices.md)** — комплексные рекомендации по организации ConfigMap в production.

### Смежные концепции и ресурсы

*   **[Secret в Kubernetes](./secrets/secrets_basics.md)** — безопасное хранение конфиденциальных данных и криптографических ключей.
*   **[Projected Volumes](./Pod/volume_types/projected_volumes.md)** — объединение ConfigMap, Secret и Downward API в единую проекцию тома.
*   **[Downward API](./Pod/downward_api.md)** — инжекция системных метаданных пода и контейнера в переменные и файлы.
*   **[Жизненный цикл Pod](./Pod/pod_lifecycle_and_state.md)** — влияние параметров конфигурации на фазы инициализации и запуска контейнеров.
*   **[Управление развертываниями (Deployment)](./Deployment/index.md)** — стратегии обновления приложений, контроль ревизий и откат.
