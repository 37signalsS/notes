# Создание ConfigMap

**Актуально для:** Kubernetes 1.28–1.32+

## Определения

**ConfigMap** — базовый объект API Kubernetes (группа API `core/v1`), предназначенный для хранения неконфиденциальных данных конфигурации в виде пар «ключ-значение». Основное назначение ресурса — реализация принципа **Separation of Concerns** (разделение ответственности) за счет изоляции конфигурационных параметров и статических файлов приложения от неизменяемых образов контейнеров.

**Поля данных объекта:**
*   **`data`** — словарь строковых данных в обязательной кодировке **UTF-8**. Ключи словаря должны соответствовать стандарту DNS-поддоменов и состоять исключительно из буквенно-цифровых символов, дефисов (`-`), символов подчеркивания (`_`) и точек (`.`) (регулярное выражение `[-._a-zA-Z0-9]+`). Значения могут быть скалярными строками, многострочными текстовыми блоками (с использованием маркеров литералов YAML `|` или `>`) либо сериализованными структурами (JSON, YAML, INI, TOML, XML).
*   **`binaryData`** — словарь двоичных данных, в котором каждое значение хранится в виде строки, закодированной в **Base64**. Используется для нетекстовых артефактов (скомпилированные бинарные модули, gzip-архивы, изображения, TLS-сертификаты без закрытых ключей). При императивном создании через CLI Kubernetes автоматически определяет бинарный контент и сохраняет его в `binaryData`.

**Хранение в etcd и лимит размера:**
ConfigMap сохраняется в распределенном хранилище `etcd` как сериализованный JSON-документ по ключу `/registry/configmaps/<namespace>/<name>`. Максимальный допустимый размер одного объекта ограничен **1 MiB** (1 048 576 байт). Этот лимит включает в себя сумму всех метаданных (`metadata.labels`, `metadata.annotations`), ключей и полезной нагрузки полей `data` и `binaryData`. Превышение лимита приводит к жесткому отклонению транзакции `kube-apiserver` с ошибкой HTTP 413 `RequestEntityTooLarge`.

**Методы создания:**
*   **Декларативный (GitOps-путь):** Описание манифестов в YAML/JSON и применение через `kubectl apply` или механизмы **Server-Side Apply (SSA)**. Обеспечивает версионирование в системе контроля версий, аудит, рецензирование кода (Code Review) и детерминированность среды.
*   **Генеративный (Automation-путь):** Динамическая генерация объектов из исходных файлов конфигурации, каталогов и литералов средствами утилит сборки (**Kustomize** с генератором `configMapGenerator` или шаблонизатором **Helm**). Позволяет автоматически формировать хеш-суффиксы имен (Name Hashing) для безопасного обновления зависимых подов.
*   **Императивный (CLI/Debug-путь):** Непосредственное создание объекта вызовом `kubectl create configmap`. Применяется для локального тестирования, быстрого прототипирования и генерации начальных манифестов через флаг `--dry-run=client -o yaml`.

**Неизменяемость (`immutable: true`):**
Спецификационный флаг (доступен в статусе GA с версии Kubernetes 1.21), блокирующий любые последующие изменения содержимого полей `data` и `binaryData` на уровне валидации API-сервера. Защищает конфигурацию от случайных модификаций операторами и снижает нагрузку на `kube-apiserver` за счет отключения периодических long-lived Watch-соединений со стороны агентов `kubelet`.

---

## Основные концепции

### Архитектура и жизненный цикл ресурса

ConfigMap является пассивным ресурсом данных: он не управляется выделенным контроллером репликации в `kube-controller-manager` и сам по себе не выполняет активных действий в кластере.

```
       +--------------------------------------------------------+
       |                  Разработчик / CI/CD                   |
       +--------------------------------------------------------+
              |                        |                  |
   Декларативный YAML          Kustomize / Helm       Императивный
  (Server-Side Apply)       (Name Hashing / tpl)    (kubectl create)
              |                        |                  |
              +---------------->       |       <----------+
                               v       v       v
                       +-------------------------------+
                       |        kube-apiserver         |
                       | (Authentication/Authorization)|
                       +-------------------------------+
                                       |
                         Validating Admission Policies
                           / Admission Controllers
                                       |
                                       v
                       +-------------------------------+
                       |             etcd              |
                       |    (Лимит объекта <= 1 MiB)   |
                       +-------------------------------+
                                       |
                   +-------------------+-------------------+
                   | (Монтирование тома)                   | (Переменные окружения)
                   v                                       v
         +--------------------+                  +--------------------+
         |   Kubelet (Node)   |                  |   Kubelet (Node)   |
         |  Atomic Symlink    |                  |  Инжекция в env    |
         |    ..data swap     |                  |  при старте пода   |
         +--------------------+                  +--------------------+
```

1. **Создание и валидация:** Запрос на создание направляется в `kube-apiserver`, проходит аутентификацию, авторизацию через RBAC, фазу мутирующих и валидирующих контроллеров допуска (включая проверку квот `ResourceQuota` и политик `ValidatingAdmissionPolicy`).
2. **Персистентность:** Валидированный объект сериализуется и записывается в `etcd`.
3. **Потребление подами:** Контейнеры связываются с ConfigMap через `volumes` (монтирование файлов в контейнер) или через `env` / `envFrom` (переменные окружения процесса).
4. **Отсутствие авто-ротации контроллеров:** Изменение содержимого существующего ConfigMap не приводит к автоматическому пересозданию подов в Deployment, StatefulSet или DaemonSet, поскольку спецификация шаблона пода (`spec.template`) контроллера остается неизменной. Для запуска Rolling Update требуется либо использование версионированных имен (Kustomize Name Hashing), либо смена аннотаций контрольной суммы (Helm `checksum/config`), либо явная команда перезапуска `kubectl rollout restart`.

### Иерархия приоритетов переменных окружения и конфигураций

При доставке параметров в контейнер приложения действует строгий порядок приоритета (от низшего к высшему):

1. **Базовый слой образа контейнера:** Переменные `ENV`, жестко зашитые в Dockerfile/OCI-образе.
2. **Пакетная инъекция `envFrom`:** Переменные, загруженные из ConfigMap или Secret через блок `envFrom`. Если указано несколько блоков `envFrom`, ключи из последующих источников перезаписывают ключи из предыдущих при их совпадении.
3. **Точечные переменные `env`:** Явно определенные параметры в блоке `spec.containers[*].env`. Они всегда переопределяют значения с идентичными именами, полученные из `envFrom` или Dockerfile.
4. **Интерполяция зависимых переменных:** Значения в `env`, использующие подстановку `$(VAR_NAME)`, раскрываются последовательно сверху вниз на основе уже сформированного окружения.
5. **Аргументы запуска контейнера (`command` и `args`):** Раскрываются агентом `kubelet` перед запуском процесса на основе сформированного окружения контейнера при синтаксисе `$(VAR_NAME)`.
6. **Конфигурационные файлы из томов (Volumes):** Файлы, смонтированные через тома, находятся на файловой системе контейнера и не влияют на переменные окружения напрямую, если только само приложение или его entrypoint-скрипт явно не вычитывает их с диска.

### Сравнение методов создания ConfigMap

| Критерий | Декларативный (YAML / SSA) | Kustomize (`configMapGenerator`) | Helm (Шаблонизация) | Императивный (`kubectl create`) |
| :--- | :--- | :--- | :--- | :--- |
| **Основное назначение** | GitOps, инфраструктура как код | Промышленный GitOps, управление средами | Упаковка и дистрибуция комплексных приложений | Прототипирование, отладка, генерация шаблонов |
| **Версионирование в Git** | Полное (хранится готовый YAML) | Полное (исходные файлы конфигов в Git) | Полное (шаблоны и `values.yaml` в Git) | Отсутствует (ручной ввод в CLI) |
| **Автоматический перезапуск подов** | Нет (требует ручного `rollout restart` или Reloader) | **Да** (автоматический суффикс Name Hash) | **Да** (через аннотацию `sha256sum`) | Нет |
| **Поддержка бинарных данных** | Требует ручного Base64 кодирования | Да (автоматическая обработка бинарных файлов) | Да (через фильтр `b64enc`) | Да (автоматическое помещение в `binaryData`) |
| **Валидация до выката** | `kubectl diff`, `--dry-run=server` | `kustomize build`, `kubeconform` | `helm template`, `helm lint` | `--dry-run=client` |
| **Сложность внедрения** | Низкая | Средняя | Средняя/Высокая | Минимальная |

### Ограничения именования ключей и ловушки сред выполнения

Существует фундаментальное различие между допустимыми ключами для томов и ключами для переменных окружения:

*   **Для монтирования томов (`volumes`):** Ключ ConfigMap становится именем файла на файловой системе. Допускаются любые символы из набора `[-._a-zA-Z0-9]+` (например, `application.production.json`, `nginx-proxy.conf`, `settings.v2.ini`).
*   **Для переменных окружения (`envFrom`):** Стандарт POSIX/C-идентификаторов для переменных окружения требует соответствия маске `[a-zA-Z_][a-zA-Z0-9_]*`. Если ключ ConfigMap содержит точки (`.`), дефисы (`-`) или начинается с цифры (например, `app-port` или `db.host`), агент `kubelet` **молча проигнорирует этот ключ** при развертывании через `envFrom`. Никакой ошибки при создании ConfigMap не возникнет, однако контейнер не получит переменную, что приведет к сбою приложения в Runtime.
*   **Для точечного связывания (`env.valueFrom.configMapKeyRef`):** Допускается использовать произвольный допустимый ключ ConfigMap (например, `database-url`), так как имя результирующей переменной окружения задается отдельно в поле `name` (например, `DATABASE_URL`).

---

## Практические сценарии

### Сценарий 1: Декларативное создание манифестов и Server-Side Apply

Декларативное описание в формате YAML — стандарт для GitOps-конвейеров.

**Манифест `backend-config.yaml`:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: backend-config
  namespace: default
  labels:
    app.kubernetes.io/name: backend-service
    app.kubernetes.io/instance: backend-prod
    app.kubernetes.io/component: api
    app.kubernetes.io/part-of: core-platform
    app.kubernetes.io/managed-by: gitops
  annotations:
    config.kubernetes.io/summary: "Параметры подключения и runtime-настройки backend API"
data:
  # Скалярные значения для переменных окружения (C-идентификаторы)
  SERVER_PORT: "8080"
  LOG_LEVEL: "info"
  METRICS_ENABLED: "true"
  DB_MAX_CONNECTIONS: "50"

  # Конфигурационные файлы для монтирования в тома
  app-settings.json: |
    {
      "connectionTimeoutMs": 5000,
      "retryPolicy": {
        "maxRetries": 3,
        "backoffBaseMs": 200
      }
    }

  nginx-upstream.conf: |
    upstream backend_pool {
        server 127.0.0.1:8080 max_fails=3 fail_timeout=10s;
        keepalive 32;
    }
```

**Применение через Client-Side Apply (традиционный метод):**
```bash
kubectl apply -f backend-config.yaml
# → configmap/backend-config created
```

**Применение через Server-Side Apply (современный производственный стандарт):**
Server-Side Apply фиксирует права владения полями (`managedFields`), проверяет схему на стороне сервера и предотвращает случайную перезапись полей разными контроллерами или администраторами.

```bash
# Применение с указанием явного field-manager
kubectl apply --server-side --field-manager=sre-deployer -f backend-config.yaml
# → configmap/backend-config serverside-applied

# Разрешение конфликтов владения полями (при необходимости принудительного захвата управления)
kubectl apply --server-side --field-manager=sre-deployer --force-conflicts -f backend-config.yaml
# → configmap/backend-config serverside-applied
```

---

### Сценарий 2: Генеративный подход через Kustomize (configMapGenerator)

Kustomize решает критическую проблему надежности: автоматический перезапуск рабочих нагрузок при изменении файлов конфигураций за счет генерации детерминированного хеш-суффикса.

**Структура каталога:**
```text
k8s/
├── configs/
│   ├── app.properties
│   └── service.conf
├── envs/
│   └── app.env
└── kustomization.yaml
```

**Файл `k8s/kustomization.yaml`:**
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

configMapGenerator:
  - name: app-runtime-config
    # 1. Загрузка из файлов: ключ = имя файла (или заданный псевдоним)
    files:
      - configs/app.properties
      - custom-proxy.conf=configs/service.conf
    # 2. Определение строковых литералов
    literals:
      - SERVICE_REGION=dc-east
      - CACHE_TTL_SECONDS=3600
    # 3. Загрузка пар ключ-значение из .env-файла
    envs:
      - envs/app.env

generatorOptions:
  # Добавление флага immutable: true во все генерируемые ConfigMap
  immutable: true
  # Управление хеш-суффиксом (по умолчанию false, хеш добавляется)
  disableNameSuffixHash: false
  labels:
    app.kubernetes.io/managed-by: kustomize
```

**Сборка и валидация манифестов без применения к кластеру:**
```bash
kubectl kustomize k8s/
```

**Ожидаемый вывод генерации:**
```yaml
apiVersion: v1
immutable: true
kind: ConfigMap
metadata:
  labels:
    app.kubernetes.io/managed-by: kustomize
  name: app-runtime-config-77k47g47hf
data:
  CACHE_TTL_SECONDS: "3600"
  SERVICE_REGION: dc-east
  app.properties: |
    thread.pool.size=16
    queue.capacity=500
  custom-proxy.conf: |
    proxy_connect_timeout 5s;
    proxy_read_timeout 60s;
  DB_POOL_MIN: "5"
  DB_POOL_MAX: "20"
```

**Переопределение генератора в оверлеях (Overlays) через `behavior`:**
При построении многоуровневых сред (Base -> Overlay) директива `behavior` управляет взаимодействием с базовой конфигурацией:
*   `behavior: create` — создание нового объекта (поведение по умолчанию).
*   `behavior: replace` — полная замена базового генератора.
*   `behavior: merge` — слияние ключей текущего оверлея с ключами базового генератора.

```yaml
# k8s/overlays/production/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../base

configMapGenerator:
  - name: app-runtime-config
    behavior: merge
    literals:
      - CACHE_TTL_SECONDS=86400
      - LOG_LEVEL=warn
```

---

### Сценарий 3: Генеративный подход через Helm

В чартах Helm ConfigMap генерируется динамически с подстановкой значений из `values.yaml` и встраиванием файлов репозитория.

**Шаблон ConfigMap `templates/configmap.yaml`:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "service.fullname" . }}-config
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "service.labels" . | nindent 4 }}
data:
  # Простые скалярные значения из values.yaml
  SERVICE_PORT: {{ .Values.config.port | quote }}
  LOG_LEVEL: {{ .Values.config.logLevel | default "info" | quote }}

  # Встраивание статического файла с корректными отступами
  server.xml: |
    {{- .Files.Get "files/server.xml" | nindent 4 }}

  # Динамическая шаблонизация содержимого внешнего файла с помощью tpl
  # Позволяет использовать Helm-синтаксис {{ .Values }} внутри самого конфигурационного файла
  app.conf: |
    {{- tpl (.Files.Get "files/app.conf.tpl") . | nindent 4 }}

  # Пакетное добавление всех файлов из каталога scripts/
  {{- range $path, $bytes := .Files.Glob "scripts/*.sh" }}
  {{ base $path }}: |
    {{- $.Files.Get $path | nindent 4 }}
  {{- end }}

binaryData:
  # Встраивание двоичных файлов (архивов, иконок) с кодированием в Base64
  {{- if .Files.Glob "files/archive.tar.gz" }}
  archive.tar.gz: {{ .Files.Get "files/archive.tar.gz" | b64enc | quote }}
  {{- end }}
```

**Шаблон Deployment с автоматическим перезапуском подов (`checksum/config`):**
При изменении любого значения или файла, входящего в ConfigMap, контрольная сумма SHA-256 в аннотации шаблона пода изменится, что запустит Rolling Update пода. Подробнее: [Helm: перезапуск при изменении конфига](../../ToolsUtilities/Helm/templating/scenarios/restart_on_change.md).

```yaml
# templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "service.fullname" . }}
spec:
  template:
    metadata:
      annotations:
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
    spec:
      containers:
        - name: app
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
```

---

### Сценарий 4: Императивное создание и прототипирование через `kubectl create`

Императивные команды применяются системными администраторами для оперативной диагностики, отладки и быстрой генерации манифестов.

**1. Создание из литералов (`--from-literal`):**
```bash
kubectl create configmap network-tuning \
  --from-literal=MAX_CLIENTS=1000 \
  --from-literal=TIMEOUT_SEC=30 \
  --namespace=default
# → configmap/network-tuning created
```

**2. Создание из отдельных файлов (`--from-file`):**
```bash
# Имя файла становится ключом в поле data
kubectl create configmap nginx-core-config \
  --from-file=/etc/nginx/nginx.conf

# Явное переопределение имени ключа для файла
kubectl create configmap nginx-custom-key \
  --from-file=custom_name.conf=/etc/nginx/nginx.conf
```

**3. Создание из каталога файлов:**
Все регулярные файлы в каталоге считываются и помещаются в `data` (имя файла = ключ). Подкаталоги игнорируются.
```bash
kubectl create configmap service-all-configs \
  --from-file=./configs/
```

**4. Создание из файла переменных окружения (`--from-env-file`):**
Синтаксис ожидает строки формата `KEY=VALUE`. Строки, начинающиеся с символа `#`, и пустые строки автоматически игнорируются.
```bash
kubectl create configmap db-params \
  --from-env-file=./production.env
```

**5. Комбинирование нескольких источников в одной команде:**
```bash
kubectl create configmap composite-config \
  --from-literal=ENVIRONMENT=production \
  --from-file=app.json=./config/app.json \
  --from-file=./config/routes/ \
  --from-env-file=./app.env
```

**6. Генерация манифеста (Dry-Run без отправки в кластер):**
```bash
# Генерация чистого YAML-манифеста на клиенте
kubectl create configmap app-template \
  --from-literal=DATABASE_PORT=5432 \
  --from-file=server.conf=./server.conf \
  --dry-run=client -o yaml > app-config.yaml

# Валидация создания на сервере (проверка прав RBAC и контроллеров допуска без сохранения в etcd)
kubectl create configmap app-template \
  --from-literal=DATABASE_PORT=5432 \
  --dry-run=server -o yaml
```

---

### Сценарий 5: Работа с двоичными данными (`binaryData`)

Поле `binaryData` предназначено для хранения артефактов, содержащих нулевые байты или последовательности, не являющиеся корректным UTF-8 текстом.

**Автоматическая обработка бинарных данных через `kubectl`:**
Если файл, переданный в `--from-file`, содержит нетекстовые символы, `kubectl` автоматически преобразует его содержимое в Base64 и помещает в секцию `binaryData`.

```bash
# Создание тестового бинарного архива
tar -czf /tmp/bundle.tar.gz -C /etc/hosts .

# Создание ConfigMap из бинарного файла
kubectl create configmap binary-assets \
  --from-file=/tmp/bundle.tar.gz

# Проверка распределения полей в API
kubectl get configmap binary-assets -o yaml
```

**Ожидаемый результат в выводе API:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: binary-assets
  namespace: default
binaryData:
  bundle.tar.gz: H4sICN6qTGcCA2hvc3RzAO3PMQ6AIBAFwD5T7A9kL0e...
```

**Ручное формирование манифеста с `binaryData`:**
```bash
# Кодирование произвольного бинарного файла в Base64 без переноса строк
CERT_B64=$(base64 -w 0 /etc/ssl/certs/internal-ca.der)

cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: internal-ca-cert
  namespace: default
binaryData:
  internal-ca.der: "${CERT_B64}"
EOF
# → configmap/internal-ca-cert created
```

---

### Сценарий 6: Создание неизменяемых ConfigMap (`immutable: true`)

В высоконагруженных кластерах частые вызовы Watch создают значительную нагрузку на `kube-apiserver` и etcd. Установка флага `immutable: true` переводит объект в режим фиксации состояния.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: platform-routing-v1
  namespace: production
  labels:
    app.kubernetes.io/name: platform-routing
    app.kubernetes.io/version: "1.0.0"
immutable: true
data:
  routes.json: |
    {
      "api/v1": "http://api-v1-service:8080",
      "api/v2": "http://api-v2-service:8080"
    }
```

**Поведение API-сервера при попытке изменения неизменяемого ConfigMap:**
```bash
# Применение манифеста
kubectl apply -f platform-routing.yaml
# → configmap/platform-routing-v1 created

# Попытка изменить данные через patch
kubectl patch configmap platform-routing-v1 --type merge -p '{"data":{"routes.json":"{}"}}'
# → Error from server (Invalid): ConfigMap "platform-routing-v1" is invalid: data: Forbidden: field is immutable when `immutable` bool is set
```

> [!NOTE]
> Метаданные неизменяемого ConfigMap (`metadata.labels`, `metadata.annotations`) **остаются доступными для редактирования**. Заблокированы исключительно поля `data` и `binaryData`. Чтобы обновить неизменяемый ConfigMap, необходимо создать новый объект с новым именем (например, `platform-routing-v2`) и обновить ссылку в спецификации пода, либо удалить старый объект и создать его заново. Подробнее: [Неизменяемые ConfigMap](./immutable.md).

---

### Сценарий 7: Продвинутые системные паттерны создания для DevOps и Sysadmin

**1. Создание ConfigMap из динамического системного вывода команды:**
Позволяет захватывать топологию инфраструктуры (например, адреса узлов кластера) в конфигурацию без сторонних инструментов.

```bash
# Захват внутренних IP-адресов узлов кластера в один ConfigMap
kubectl create configmap cluster-nodes-inventory \
  --from-literal=INTERNAL_IPS="$(kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}:{.status.addresses[?(@.type=="InternalIP")].address}{"\n"}{end}')" \
  --dry-run=client -o yaml | kubectl apply -f -
```

**2. Создание манифестов для каталогов со вложенной иерархией:**
Команда `kubectl create configmap --from-file=<dir>` не обрабатывает подкаталоги рекурсивно. Для генерации ConfigMap из вложенных структур применяется bash-конвейер:

```bash
# Создание ConfigMap, где ключи соответствуют относительным путям ко всем вложенным файлам
cat <<'EOF' > generate-tree-cm.sh
#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="./nested-configs"
CM_NAME="tree-config"
NAMESPACE="default"

ARGS=()
while IFS= read -r -d '' file; do
  rel_path="${file#$TARGET_DIR/}"
  # Замена недопустимых символов путей на дефисы для формирования допустимого ключа
  safe_key="${rel_path//\//__}"
  ARGS+=("--from-file=${safe_key}=${file}")
done < <(find "$TARGET_DIR" -type f -print0)

kubectl create configmap "$CM_NAME" "${ARGS[@]}" -n "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
EOF
chmod +x generate-tree-cm.sh
```

---

## Операции и команды

### Сводная таблица команд управления ConfigMap

| Действие | Команда | Назначение / Особенности |
| :--- | :--- | :--- |
| **Создание** | `kubectl apply -f cm.yaml` | Декларативное создание или обновление |
| **Server-Side Apply** | `kubectl apply --server-side --field-manager=<name> -f cm.yaml` | Серверное применение с отслеживанием полей |
| **Императивное создание** | `kubectl create configmap <name> --from-literal=k=v` | Создание объекта из литералов или файлов |
| **Генерация YAML** | `kubectl create configmap <name> --from-file=... --dry-run=client -o yaml` | Получение манифеста без отправки в API |
| **Валидация на сервере** | `kubectl apply -f cm.yaml --dry-run=server` | Проверка схемы и Admission Controllers |
| **Аудит изменений** | `kubectl diff -f cm.yaml` | Сравнение локального файла с состоянием в etcd |
| **Просмотр списка** | `kubectl get configmaps -A -o wide` | Список объектов во всех пространствах имен |
| **Чтение данных** | `kubectl get configmap <name> -o yaml` | Полный вывод объекта в формате YAML |
| **Извлечение ключа** | `kubectl get cm <name> -o jsonpath='{.data.KEY_NAME}'` | Извлечение содержимого конкретного ключа |
| **Точечный патч** | `kubectl patch cm <name> --type merge -p '{"data":{"K":"V"}}'` | Быстрое обновление одного или нескольких ключей |
| **Замена объекта** | `kubectl replace -f cm.yaml` | Полная перезапись объекта (требует совпадения) |
| **Удаление** | `kubectl delete configmap <name>` | Удаление объекта из etcd |

### Диагностика, извлечение и валидация через CLI

**1. Извлечение списка всех ключей ConfigMap без вывода их содержимого:**
```bash
kubectl get configmap backend-config -o jsonpath='{.data}' | jq 'keys'
# → [
# →   "DB_MAX_CONNECTIONS",
# →   "LOG_LEVEL",
# →   "METRICS_ENABLED",
# →   "SERVER_PORT",
# →   "app-settings.json",
# →   "nginx-upstream.conf"
# → ]
```

**2. Быстрое декодирование бинарных данных из `binaryData`:**
```bash
kubectl get configmap binary-assets -o jsonpath='{.binaryData.bundle\.tar\.gz}' | base64 -d | tar -tvzf -
```

**3. Экспорт «чистого» манифеста для переноса между кластерами и пространствами имен:**
Исключает системные поля метаданных (`uid`, `resourceVersion`, `generation`, `creationTimestamp`, `managedFields`), оставляя только переносимую конфигурацию:

```bash
kubectl get configmap backend-config --namespace=default -o json | jq '
  del(.metadata.namespace, 
      .metadata.uid, 
      .metadata.resourceVersion, 
      .metadata.generation, 
      .metadata.creationTimestamp, 
      .metadata.managedFields,
      .metadata.selfLink)
' | kubectl apply --namespace=staging -f -
# → configmap/backend-config created
```

---

## Диагностика и устранение неполадок

### Типичные ошибки при создании и методы их решения

| Код / Текст ошибки | Причина сбоя | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| `RequestEntityTooLarge` (HTTP 413) | Суммарный объем ConfigMap превысил системный лимит etcd в 1 MiB (1 048 576 байт). | `kubectl get cm <name> -o json \| wc -c` или замер размера исходных файлов `ls -lh`. | Разбить конфигурацию на несколько ConfigMap, вынести файлы в `PersistentVolume` или использовать внешнее хранилище. Подробнее: [Работа с большими конфигурациями](./large_configs.md). |
| `data: Invalid value: ...: must be valid UTF-8 string` | Попытка передать бинарный файл или текст с недопустимыми UTF-8 байтами в поле `data`. | Выполнить проверку кодировки файла: `file -i <filename>` или `iconv -f utf-8 -t utf-8 <filename>`. | Использовать поле `binaryData` с Base64 кодированием либо утилиту `kubectl create cm --from-file`, которая автоматически поместит файл в `binaryData`. |
| `ApplyConflict` (HTTP 409) при Server-Side Apply | Конфликт прав владения: поле в ConfigMap уже управляется другим менеджером (например, Helm или другим пользователем). | `kubectl get cm <name> -o jsonpath='{.metadata.managedFields}' \| jq .` | Применить манифест с флагом `--force-conflicts`, если необходимо принудительно забрать права владения полем. |
| Пропуск переменных окружения контейнером (тихий сбой) | Ключи в ConfigMap содержат точки или дефисы (`db.host`, `app-port`), из-за чего агент `kubelet` пропускает их при монтировании через `envFrom`. | Проверить окружение внутри пода: `kubectl exec <pod> -- env` и сравнить с ключами в ConfigMap. | Переименовать ключи в формат C-идентификаторов (`DB_HOST`, `APP_PORT`) или использовать точечное подключение через `spec.containers[*].env`. |
| `CreateContainerConfigError` | Под ссылается на несуществующий ConfigMap или отсутствующий ключ при `optional: false` (по умолчанию). | `kubectl describe pod <pod-name>` в секции `Events`. | Создать отсутствующий ConfigMap до запуска пода или указать флаг `optional: true` в спецификации ссылки на ConfigMap. Подробнее: [CreateContainerConfigError](./../../Troubleshooting/Common_Errors/CreateContainerConfigError/configmap_issues.md). |
| `Forbidden` (HTTP 403) | У субъекта (User или ServiceAccount) отсутствуют права RBAC на вызов `create` для ресурса `configmaps`. | `kubectl auth can-i create configmaps --as=<user> -n <ns>` | Предоставить права в целевом пространстве имен через Role и RoleBinding. |
| `field is immutable when immutable bool is set` | Попытка изменить поля `data` или `binaryData` у ConfigMap, созданного с флагом `immutable: true`. | `kubectl get cm <name> -o jsonpath='{.immutable}'` | Создать новый ConfigMap с новым именем (Name Hashing) или удалить старый объект и создать заново. |

### Пошаговая диагностика сбоя при создании ConfigMap

Если манифест ConfigMap отклоняется при создании:

```bash
# Шаг 1: Проверка синтаксиса и схемы объекта офлайн с помощью kubeconform
kubeconform -strict -kubernetes-version 1.30.0 backend-config.yaml
# → backend-config.yaml - ConfigMap backend-config is valid

# Шаг 2: Выполнение валидации на стороне API-сервера без записи в etcd
kubectl apply -f backend-config.yaml --dry-run=server
# → Если запрос отклонён, вывод покажет ошибку конкретного Admission Controller или Quota

# Шаг 3: Проверка размера генерируемого объекта в байтах
kubectl create configmap check-size --from-file=./configs/ --dry-run=client -o json | wc -c
# → Результат должен быть строго меньше 1048576 байт
```

---

## Рекомендации и лучшие практики

*   **Приоритет неизменяемости (Immutability-First):** Для всех стабильных рабочих нагрузок всегда устанавливайте флаг `immutable: true`. Это гарантирует отсутствие неконтролируемого дрейфа конфигурации (Configuration Drift) и снимает нагрузку с control plane кластера за счет отключения Watch в Kubelet.
*   **Использование Name Hashing:** В производственных пайплайнах генерируйте имена ConfigMap с хеш-суффиксами содержимого (`configMapGenerator` в Kustomize или расчет хеша в CI/CD). Это гарантирует предсказуемый Rolling Update подов и возможность мгновенного отката на предыдущий ReplicaSet со старой конфигурацией.
*   **Изоляция сред по пространствам имен (Namespaces):** Никогда не добавляйте суффиксы сред в имя объекта (`app-config-prod`, `app-config-stage`). Имя ресурса должно быть стабильным (`app-config`), а разделение между Dev, Stage и Prod должно происходить исключительно на уровне Namespaces.
*   **Строгое разграничение чувствительных данных:** Запрещается сохранять пароли, приватные ключи, токены и сертификаты безопасности в ConfigMap. Используйте специализированные объекты [Secret](../secrets/secrets_basics.md).
*   **Валидация в CI/CD-пайплайнах:** Проверяйте манифесты линтерами (`kubeconform -strict`) и выполняйте проверку через `kubectl diff` и `--dry-run=server` до применения в production-окружении.
*   **Соблюдение соглашений именования ключей:** Для файлов используйте реальные имена (`nginx.conf`), для переменных окружения — исключительно валидные C-идентификаторы в верхнем регистре (`DATABASE_URL`).
*   **Автоматизация очистки осиротевших (Orphaned) ConfigMap:** При частом развертывании версионированных ConfigMap со временем накапливаются неиспользуемые объекты. Ниже приведен bash-скрипт для обнаружения ConfigMap, на которые не ссылается ни один под в пространстве имен:

```bash
#!/usr/bin/env bash
# Поиск ConfigMap, не используемых ни одним активным подом в namespace
set -euo pipefail

NAMESPACE="${1:-default}"

echo "Анализ неиспользуемых ConfigMap в namespace: $NAMESPACE"

# Получение списка используемых ConfigMap из спецификаций Pods
USED_CMS=$(kubectl get pods -n "$NAMESPACE" -o json | jq -r '
  .items[] | 
  (
    (.spec.volumes[]?.configMap?.name // empty),
    (.spec.containers[].env[]?.valueFrom?.configMapKeyRef?.name // empty),
    (.spec.containers[].envFrom[]?.configMapRef?.name // empty),
    (.spec.initContainers[]?.env[]?.valueFrom?.configMapKeyRef?.name // empty),
    (.spec.initContainers[]?.envFrom[]?.configMapRef?.name // empty)
  )
' | sort -u)

# Получение всех существующих ConfigMap (исключая системный kube-root-ca.crt)
ALL_CMS=$(kubectl get configmaps -n "$NAMESPACE" -o json | jq -r '
  .items[].metadata.name | select(. != "kube-root-ca.crt")
' | sort -u)

# Вычисление разницы
comm -23 <(echo "$ALL_CMS") <(echo "$USED_CMS") | while read -r orphan; do
  echo "Осиротевший ConfigMap: $orphan"
done
```

---

## Дополнительная информация

### Автоматизация в CI/CD пайплайнах

#### Пример пайплайна в GitLab CI
```yaml
# .gitlab-ci.yml
stages:
  - test
  - deploy

validate-configmaps:
  stage: test
  image: alpine/k8s:1.30.2
  script:
    - kubeconform -strict -schema-location default k8s/
    - kubectl apply -k k8s/overlays/production/ --dry-run=server

deploy-configmaps:
  stage: deploy
  image: alpine/k8s:1.30.2
  script:
    - kubectl apply -k k8s/overlays/production/
    - kubectl rollout status deployment/backend-api -n production --timeout=120s
  only:
    - main
```

#### Пример шага в GitHub Actions
```yaml
# .github/workflows/deploy.yaml
name: Deploy Configuration
on:
  push:
    paths:
      - 'k8s/configs/**'

jobs:
  validate-and-apply:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install kubeconform
        run: |
          curl -sL https://github.com/yannh/kubeconform/releases/latest/download/kubeconform-linux-amd64.tar.gz | tar xz
          sudo mv kubeconform /usr/local/bin/

      - name: Lint Kubernetes Manifests
        run: kubeconform -strict -summary k8s/configs/

      - name: Apply Configuration
        run: |
          kubectl apply --server-side --field-manager=github-actions -f k8s/configs/
```

---

### Мониторинг, алертинг и аудит (SRE)

#### Мониторинг ошибок создания через метрики kube-apiserver
Метрика `apiserver_request_total` позволяет отслеживать частоту ошибок создания ConfigMap (HTTP 4xx/5xx) на уровне API-сервера:

```yaml
# PrometheusRule: Оповещение об аномальном количестве ошибок при создании ConfigMap
- alert: KubeApiServerConfigMapCreateErrors
  expr: |
    sum(rate(apiserver_request_total{resource="configmaps",verb="create",code=~"4..|5.."}[5m]))
    /
    sum(rate(apiserver_request_total{resource="configmaps",verb="create"}[5m])) > 0.05
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "Высокий уровень ошибок при создании ConfigMap"
    description: "Более 5% запросов на создание ConfigMap завершаются ошибками в течение последних 5 минут."
```

#### Отслеживание удаления и жизненного цикла через kube-state-metrics
Метрика `kube_configmap_created` передает Unix-timestamp создания объекта:

```yaml
# PrometheusRule: Обнаружение удаления критически важного ConfigMap
- alert: CriticalConfigMapDeleted
  expr: |
    (kube_configmap_created{configmap="backend-config",namespace="production"} offset 5m)
    unless
    kube_configmap_created{configmap="backend-config",namespace="production"}
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "Критический ConfigMap удален"
    description: "ConfigMap backend-config в namespace production был удален из кластера."
```

#### Аудит создания объектов через Kubernetes Audit Logs
Фрагмент политики аудита для логирования фактов создания и изменения объектов ConfigMap:

```yaml
# audit-policy.yaml
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
  - level: RequestResponse
    verbs: ["create", "update", "patch", "delete"]
    resources:
      - group: ""
        resources: ["configmaps"]
    namespaces: ["production"]
```

---

### Безопасность и RBAC

#### Роль с минимальными правами для управления ConfigMap
Для сервисных учетных записей (ServiceAccount) или инженеров следует предоставлять только необходимые глаголы:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: default
  name: configmap-manager
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: bind-configmap-manager
  namespace: default
subjects:
  - kind: ServiceAccount
    name: cicd-deployer
    namespace: default
roleRef:
  kind: Role
  name: configmap-manager
  apiGroup: rbac.authorization.k8s.io
```

#### Защита от утечки секретов через ValidatingAdmissionPolicy (Kubernetes 1.30+ GA)
Декларативная политика на базе языка CEL (Common Expression Language), запрещающая создание ConfigMap, содержащих ключи или строки с признаками паролей и токенов:

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: "block-secrets-in-configmap"
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["configmaps"]
  validations:
    - expression: "!object.data.exists(k, k.matches('(?i).*(password|secret|token|private_key|apikey).*'))"
      message: "Запрещено хранить секретные данные (пароли, токены, ключи) в ConfigMap. Используйте объект Secret."
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: "block-secrets-in-configmap-binding"
spec:
  policyName: "block-secrets-in-configmap"
  validationActions: [Deny]
  matchResources:
    namespaceSelector:
      matchExpressions:
        - key: kubernetes.io/metadata.name
          operator: NotIn
          values: ["kube-system"]
```

---

**См. также:**

* [Лучшие практики ConfigMap](./best_practices.md) — стандарты именования, маркировка и архитектурные правила.
* [Использование ConfigMap в подах](./pod_usage.md) — способы монтирования томов, инъекция переменных окружения и механизм атомарных симлинков.
* [Неизменяемые ConfigMap](./immutable.md) — оптимизация Control Plane и Kubelet через `immutable: true`.
* [Обновление и Rollout](./update_and_rollout.md) — задержки распространения, стратегии перезапуска и работа без простоя.
* [Работа с большими конфигурациями](./large_configs.md) — обход лимита 1 MiB с помощью томов и внешних хранилищ.
* [Готовые шаблоны ConfigMap](./practical_templates.md) — проверенные конфигурации для Nginx, Prometheus, PostgreSQL.
* [Kustomize обзор](../../ToolsUtilities/kustomize/kustomize_overview.md) — основы декларативного управления конфигурациями и оверлеями.
* [Helm: перезапуск при изменении конфига](../../ToolsUtilities/Helm/templating/scenarios/restart_on_change.md) — управление контрольными суммами конфигураций.
* [Диагностика CreateContainerConfigError](../../Troubleshooting/Common_Errors/CreateContainerConfigError/configmap_issues.md) — решение проблем при невозможности разрешения ссылок на ConfigMap.
* [Контроллеры допуска](../../Concepts/admission_controllers.md) — валидация и мутация объектов при создании.
* [Secret основы](../secrets/secrets_basics.md) — безопасное хранение чувствительных данных в кластере.
