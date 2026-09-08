# Создание ConfigMap

## Определения

**ConfigMap** — объект API Kubernetes, предназначенный для хранения неконфиденциальных конфигурационных данных в виде пар «ключ-значение». Он позволяет отделить конфигурацию от кода приложения, обеспечивая переносимость образов контейнеров между различными окружениями и соблюдение принципа **Separation of Concerns**.

### Структура данных

ConfigMap поддерживает два типа данных:

*   **`data`** — текстовые строки в кодировке **UTF-8**. Каждый ключ должен быть уникальным в пределах объекта. Значения могут быть простыми строками, многострочными блоками (символ `|`) или структурированными данными (JSON, YAML).
*   **`binaryData`** — бинарные данные, закодированные в **Base64**. Используется для файлов, не являющихся текстом UTF-8 (сертификаты, изображения, скомпилированные артефакты). При использовании `kubectl create configmap --from-file` для бинарных файлов инструмент автоматически помещает их в `binaryData`.

### Хранение в etcd

ConfigMap хранится в etcd как объект Kubernetes API. Данные записываются в поля `data` и `binaryData` JSON-представления объекта. Ограничение в **1 MiB** связано с рекомендациями по размеру объектов etcd для обеспечения производительности кластера. При превышении этого лимита API-сервер отклоняет запрос с ошибкой `RequestEntityTooLarge`.

## Основные концепции

### Методы создания

Управление жизненным циклом ConfigMap осуществляется тремя основными способами:

1.  **Декларативный (GitOps-путь):** Описание состояния через YAML-манифесты. Обеспечивает версионирование, аудит и Code Review конфигураций.
2.  **Генеративный (Automation-путь):** Использование инструментов (Kustomize, Helm) для динамического создания объектов из внешних источников (файлов, переменных окружения). В Kustomize этот метод считается стандартом (Name Hashing), так как он автоматически инициирует обновление подов при изменении данных.
3.  **Императивный (Debug-путь):** Создание через команды `kubectl create`. Применяется для быстрого прототипирования, отладки или генерации начальных YAML-шаблонов.

### Порядок приоритета переменных

При одновременном использовании разных способов передачи данных действует следующий приоритет:

1.  **Переменные окружения (`env`)** — переопределяют значения из `envFrom`.
2.  **`envFrom`** — загружает все ключи из ConfigMap/Secret.
3.  **Тома (Volumes)** — файлы монтируются отдельно, не конфликтуют с переменными окружения.

### Важные ограничения

*   **Namespace Scope:** ConfigMap является ресурсом уровня пространства имен. Поды могут использовать только те ConfigMap, которые находятся в том же Namespace.
*   **Лимит размера:** Максимальный размер одного объекта ограничен **1 MiB** (ограничение хранилища etcd). При превышении API-сервер отклоняет запрос с ошибкой `RequestEntityTooLarge`.
*   **Кодировка:** Поле `data` поддерживает только строки в кодировке **UTF-8**. Для бинарных данных используется `binaryData`.
*   **Атомарность:** При монтировании как тома Kubernetes гарантирует атомарность обновления через механизм символических ссылок (см. раздел «Механизм атомарного обновления» в [pod_usage.md](./pod_usage.md)).

## Практические сценарии

### Декларативный подход: YAML-манифест

Стандарт для Production-окружений. Позволяет описывать как простые ключи, так и целые файлы конфигурации.

```yaml
# app-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
  namespace: prod
  labels:
    app: backend
    tier: middle
  annotations:
    description: "Основная конфигурация backend-сервиса"
    last-modified-by: "devops-team"
data:
  # Простые пары ключ-значение
  DB_PORT: "5432"
  LOG_LEVEL: "INFO"
  
  # Многострочный блок конфигурации
  server.conf: |
    server {
        timeout: 30s
        max_connections: 100
    }
  
  # JSON-конфигурация
  app-config.json: |
    {
      "features": {
        "enable_logging": true,
        "max_retries": 3
      }
    }
  
  # YAML-конфигурация
  config.yaml: |
    database:
      host: db.example.com
      port: 5432
      pool:
        min: 5
        max: 20
```

**Применение:**
```bash
kubectl apply -f app-config.yaml
# → configmap/app-config created
```

---

### Генеративный подход: Kustomize (configMapGenerator)

Kustomize (встроен в `kubectl -k`) автоматизирует создание ConfigMap и управление их версиями через **Name Hashing**. При изменении содержимого файлов Kustomize генерирует новое имя (например, `app-config-f7h8z9`), что вынуждает Kubernetes выполнить Rolling Update для всех зависимых Deployments.

```yaml
# kustomization.yaml
configMapGenerator:
- name: app-config
  # Создание из файлов (имя файла станет ключом)
  files:
    - configs/nginx.conf
    - configs/app.properties
  # Создание из литералов
  literals:
    - API_ENDPOINT=https://api.internal.local
  # Создание из .env файла
  envs:
    - .env.prod

generatorOptions:
  # Установка флага неизменяемости (Best Practice)
  immutable: true
  labels:
    managed-by: kustomize
```

---

### Императивный подход: kubectl create

Используется для быстрой генерации объектов «на лету» или создания шаблонов.

**Создание из различных источников:**
```bash
# Из литералов (явные пары ключ=значение)
kubectl create configmap my-lite --from-literal=DEBUG=true --from-literal=COLOR=red

# Из конкретного файла (имя файла станет ключом)
kubectl create configmap my-file --from-file=config.yaml

# С явным указанием ключа для файла
kubectl create configmap my-key --from-file=custom_key=path/to/real_file.txt

# Из директории (все файлы в директории станут ключами)
kubectl create configmap my-dir --from-file=./configs/

# Из .env файла
kubectl create configmap my-env --from-env-file=.env
```

**Генерация манифеста (Dry-run):**
```bash
# Получение YAML-шаблона без создания объекта в кластере
kubectl create configmap app-template --from-literal=key=value --dry-run=client -o yaml > cm.yaml

# Валидация на стороне сервера (проверка Admission Controllers)
kubectl create configmap app-template --from-literal=key=value --dry-run=server -o yaml > cm.yaml
```

**Создание из нескольких файлов:**
```bash
# Несколько файлов за одну команду
kubectl create configmap multi-file \
  --from-file=config/nginx.conf \
  --from-file=config/app.properties \
  --from-file=config/logging.yaml

# Все файлы из директории (включая поддиректории)
kubectl create configmap all-configs --from-file=./configs/ --recursive
```

**Создание из .env файла с явным указанием ключа:**
```bash
# Использование конкретного ключа вместо имени файла
kubectl create configmap env-config --from-file=app_env=.env.production
```

---

### Генеративный подход: Helm

Helm предоставляет несколько способов создания ConfigMap:

**Создание через встроенные функции:**
```yaml
# templates/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-config
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
data:
  # Использование значений из values.yaml
  LOG_LEVEL: {{ .Values.config.logLevel | quote }}
  DB_HOST: {{ .Values.database.host | quote }}
  
  # Вставка содержимого файла
  nginx.conf: |
    {{- .Files.Get "configs/nginx.conf" | nindent 4 }}
    
  # Вставка бинарных данных
  logo.png: {{ .Files.Get "assets/logo.png" | b64enc | quote }}
```

**Автоматическое обновление при изменении конфигурации:**
```yaml
# templates/deployment.yaml
spec:
  template:
    metadata:
      annotations:
        # Аннотация с хешем ConfigMap для автоматического перезапуска
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
```

**Создание через helper-функции:**
```yaml
# templates/_helpers.tpl
{{- define "myapp.configMap" -}}
{{- $files := .Files -}}
{{- range $key, $value := $files.Glob "configs/*" }}
{{ $key }}: |
{{ $value | nindent 2 }}
{{- end }}
{{- end -}}
```

---

### Работа с бинарными данными (binaryData)

Для хранения файлов, не являющихся текстом в UTF-8 (сертификаты, изображения, скомпилированные артефакты), используется поле `binaryData`. Данные должны быть закодированы в **Base64**.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: binary-assets
binaryData:
  logo.png: "iVBORw0KGgoAAAANSUh..."
```

*Примечание: При использовании `kubectl create configmap --from-file` для бинарных файлов, инструмент автоматически помещает их в `binaryData`.*

---

### Неизменяемые (Immutable) ConfigMap

Начиная с Kubernetes v1.21, для оптимизации производительности рекомендуется использовать флаг `immutable: true`.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: static-settings
immutable: true
data:
  VERSION: "1.2.0"
```

**Преимущества:**
*   **Снижение нагрузки на API-сервер:** Kubelet перестает отслеживать изменения (Watch) этого ресурса.
*   **Безопасность:** Защита от случайных ручных правок (`kubectl edit`).
*   **Предсказуемость:** Обновление конфигурации гарантированно требует создания нового объекта и перезапуска подов.

---

## Управление существующими ConfigMap

### Просмотр и диагностика

```bash
# Список всех ConfigMap в Namespace
kubectl get configmap
# → NAME               DATA   AGE
# → app-config         3      2d
# → kube-root-ca.crt   1      30d

# Детальная информация о ConfigMap
kubectl describe configmap app-config

# Просмотр содержимого в формате YAML
kubectl get configmap app-config -o yaml

# Просмотр конкретного ключа через JSONPath
kubectl get configmap app-config -o jsonpath='{.data.DB_PORT}'
# → 5432

# Просмотр всех ключей (без значений)
kubectl get configmap app-config -o jsonpath='{.data}' | jq 'keys'
# → [ "DB_PORT", "LOG_LEVEL", "server.conf" ]

# Просмотр в табличном формате
kubectl get configmap app-config -o custom-columns=NAME:.metadata.name,DATA:.data

# Поиск ConfigMap по метке
kubectl get configmap -l app=backend

# Поиск ConfigMap с определенным ключом
kubectl get configmap -o json | jq '.items[] | select(.data.DB_PORT != null)'
```

### Редактирование

```bash
# Интерактивное редактирование в системном редакторе
kubectl edit configmap app-config

# Обновление конкретного ключа через kubectl patch
kubectl patch configmap app-config --type merge \
  -p '{"data":{"LOG_LEVEL":"DEBUG"}}'

# Обновление нескольких ключей
kubectl patch configmap app-config --type merge \
  -p '{"data":{"LOG_LEVEL":"DEBUG","DB_PORT":"5433"}}'

# Замена всего ConfigMap из файла (полная перезапись)
kubectl replace -f app-config.yaml

# Обновление с сохранением текущего состояния (recommended)
kubectl apply -f app-config.yaml
```

### Удаление

```bash
# Удаление конкретного ConfigMap
kubectl delete configmap app-config

# Удаление из файла
kubectl delete -f app-config.yaml

# Удаление с указанием Namespace
kubectl delete configmap app-config -n production

# Массовое удаление по метке
kubectl delete configmap -l app=backend

# Удаление с таймаутом (для ожидания завершения)
kubectl delete configmap app-config --timeout=30s
```

### Экспорт и импорт

```bash
# Экспорт ConfigMap в YAML-файл
kubectl get configmap app-config -o yaml > app-config-exported.yaml

# Экспорт с удалением системных полей (для использования в других кластерах)
kubectl get configmap app-config -o yaml | \
  kubectl neat --filename - > app-config-clean.yaml

# Импорт ConfigMap из YAML-файла
kubectl apply -f app-config-exported.yaml

# Копирование ConfigMap между Namespace
kubectl get configmap app-config -o yaml | \
  kubectl apply --namespace=production -f -

# Копирование ConfigMap между кластерам
kubectl --context=cluster-a get configmap app-config -o yaml | \
  kubectl --context=cluster-b apply -f -
```

## Дополнительная информация

### Валидация и проверка

Перед применением изменений рекомендуется выполнить следующие проверки:

1.  **Предварительный просмотр изменений:**
    ```bash
    kubectl diff -f cm.yaml
    ```

2.  **Валидация на стороне сервера (Server-side dry-run):**
    Проверяет манифест через **[Admission Controllers](../../Concepts/admission_controllers.md)** (например, лимиты Quota или политики безопасности) без записи в etcd.
    ```bash
    kubectl apply -f cm.yaml --dry-run=server
    ```

3.  **Проверка структуры данных:**
    ```bash
    kubectl get configmap <name> -o yaml
    # Проверка конкретного ключа
    kubectl get cm <name> -o jsonpath='{.data.DB_PORT}'
    ```

4.  **Проверка через kubectl explain (быстрая справка):**
    ```bash
    # Просмотр описания полей ConfigMap
    kubectl explain configmap
    
    # Просмотр структуры поля data
    kubectl explain configmap.data
    
    # Просмотр структуры поля binaryData
    kubectl explain configmap.binaryData
    ```

5.  **Валидация YAML-синтаксиса (вне кластера):**
    ```bash
    # Использование kubeconform для проверки схемы
    kubeconform -strict configmap.yaml
    
    # Использование kubesec для анализа безопасности
    kubesec scan configmap.yaml
    ```

### Типичные ошибки при создании

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Error from server (NotFound): the server could not find the requested resource` | Неверный apiVersion или kind | Проверьте `apiVersion: v1` и `kind: ConfigMap` |
| `Error from server (BadRequest): configmap in version "v1" is not yet supported` | Устаревший кластер | Обновите кластер до поддерживаемой версии |
| `Request Entity Too Large` | Размер ConfigMap превышает 1 MiB | Разбейте на несколько объектов или используйте PersistentVolume |
| `Error from server (Conflict): configmaps "x" already exists` | Попытка создания существующего объекта | Используйте `kubectl apply` вместо `kubectl create` |
| `Error from server (Forbidden): configmaps "x" is forbidden` | Недостаточно прав RBAC | Проверьте ClusterRole/Role и RoleBinding |

### Сравнение методов создания

| Метод | Уровень контроля | Авто-обновление подов | Сфера применения |
| :--- | :--- | :--- | :--- |
| **YAML (Declarative)** | Высокий | Нет (ручной рестарт) | Базовые настройки, GitOps |
| **Kustomize** | Средний | **Да** (Name Hashing) | Production, CI/CD пайплайны |
| **Helm** | Высокий | Да (через аннотации с хешем) | Сложные чарты с логикой |
| **kubectl (Imperative)** | Низкий | Нет | Отладка, генерация шаблонов |

### Рекомендации (2024-2026)

*   **Предпочитайте неизменяемость:** Используйте `immutable: true` для всех стабильных конфигураций.
*   **Используйте Name Hashing:** Это единственный надежный способ гарантировать, что все реплики приложения используют актуальную версию конфига.
*   **Контролируйте размер:** Если размер конфигурации приближается к 1 MiB, разделите её на несколько ConfigMap или используйте тома (PVC).
*   **Разделяйте данные:** Не смешивайте настройки разных приложений в одном ConfigMap. Один сервис — один (или несколько) ConfigMap.
*   **Не храните секреты:** Для паролей, ключей и токенов всегда используйте [Secret](../secrets/secrets_basics.md).
*   **Используйте `kubectl apply`:** Предпочтительнее `kubectl create` для управления конфигурацией, так как обеспечивает идемпотентность и отслеживание изменений.
*   **Валидируйте перед применением:** Всегда проверяйте манифесты с помощью `kubectl diff` и `--dry-run=server`.
*   **Документируйте изменения:** Добавляйте аннотации с описанием изменений для аудита:
    ```yaml
    metadata:
      annotations:
        description: "Увеличен таймаут подключения к БД"
        last-modified-by: "devops-team"
    ```

### Интеграция с CI/CD

#### GitHub Actions

```yaml
# .github/workflows/deploy-config.yaml
name: Deploy ConfigMap
on:
  push:
    paths:
      - 'k8s/configs/**'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Validate ConfigMap
        run: |
          kubeconform -strict k8s/configs/*.yaml
          
      - name: Apply ConfigMap
        run: |
          kubectl apply -f k8s/configs/
          
      - name: Verify Update
        run: |
          kubectl rollout status deployment/app-deployment
```

#### GitLab CI

```yaml
# .gitlab-ci.yml
stages:
  - validate
  - deploy

validate-config:
  stage: validate
  script:
    - kubeconform -strict k8s/configs/*.yaml
    - kubectl apply -f k8s/configs/ --dry-run=server

deploy-config:
  stage: deploy
  script:
    - kubectl apply -f k8s/configs/
    - kubectl rollout restart deployment/app-deployment
  only:
    - main
```

### Мониторинг и алертинг

#### Prometheus-метрики для отслеживания изменений

```yaml
# Мониторинг изменений ConfigMap через Kubernetes API
- alert: ConfigMapChanged
  expr: |
    changes(kubernetes_configmap_info[5m]) > 0
  for: 1m
  labels:
    severity: info
  annotations:
    summary: "ConfigMap {{ $labels.name }} был изменен"
    description: "ConfigMap в namespace {{ $labels.namespace }} изменен в последние 5 минут"
```

#### Отслеживание ошибок создания

```yaml
# Алерт на ошибки создания ConfigMap
- alert: ConfigMapCreationFailed
  expr: |
    kubernetes_client_requests_total{verb="create", resource="configmaps", code=~"4..|5.."} > 0
  for: 0m
  labels:
    severity: warning
  annotations:
    summary: "Ошибка создания ConfigMap"
    description: "Не удалось создать ConfigMap: {{ $labels.namespace }}/{{ $labels.name }}"
```

### Безопасность при создании

#### Проверка прав доступа

```bash
# Проверка прав на создание ConfigMap
kubectl auth can-i create configmap --namespace=production
# → yes

# Проверка прав конкретного ServiceAccount
kubectl auth can-i create configmap \
  --as=system:serviceaccount:production:app-sa \
  --namespace=production
# → yes

# Просмотр всех разрешений ServiceAccount
kubectl auth can-i --list --as=system:serviceaccount:production:app-sa
```

#### Защита от несанкционированных изменений

```yaml
# Использование Admission Controller для защиты ConfigMap
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: configmap-validator
webhooks:
  - name: validate-configmap.k8s.io
    rules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["configmaps"]
    failurePolicy: Fail
```

#### Очистка неиспользуемых ConfigMap

```bash
# Поиск ConfigMap, не используемых ни одним подом
kubectl get configmap -A -o json | jq -r '
  .items[] | 
  select(.metadata.name | test("^kube-root-ca.crt$") | not) |
  .metadata.name + " " + .metadata.namespace
' | while read name ns; do
  # Проверка использования в подах
  if ! kubectl get pods -n "$ns" -o json | jq -e "
    .items[] | 
    .spec.containers[].env[]? | 
    select(.valueFrom.configMapKeyRef.name == \"$name\")
  " > /dev/null 2>&1; then
    echo "ConfigMap $ns/$name не используется"
  fi
done

# Удаление старых ConfigMap (осторожно!)
kubectl delete configmap old-config --namespace=production
```

**См. также:**

* [Лучшие практики ConfigMap](./best_practices.md) — нейминг, структура и организация.
* [Использование ConfigMap в подах](./pod_usage.md) — монтирование и переменные окружения.
* [Неизменяемые ConfigMap](./immutable.md) — глубокое погружение в оптимизацию.
* [Обновление и Rollout](./update_and_rollout.md) — стратегии актуализации настроек без простоя.
* [Работа с большими конфигурациями](./large_configs.md) — обход лимита 1 MiB.
* [Готовые шаблоны ConfigMap](./practical_templates.md) — шаблоны для Nginx, Prometheus, Postgres.

### Продвинутые паттерны

#### Создание ConfigMap из вывода команды

```bash
# Создание ConfigMap из вывода команды (например, список IP-адресов)
kubectl create configmap ip-whitelist \
  --from-literal=ips="$(kubectl get nodes -o jsonpath='{.items[*].status.addresses[?(@.type=="InternalIP")].address}')"
```

#### Генерация ConfigMap изหลาย источников

```bash
# Комбинирование разных источников в одной команде
kubectl create configmap combined-config \
  --from-literal=DB_HOST=postgres.local \
  --from-literal=DB_PORT=5432 \
  --from-file=config/nginx.conf \
  --from-env-file=.env.production
```

#### Использование kubectl diff для отслеживания изменений

```bash
# Просмотр изменений перед применением
kubectl diff -f app-config.yaml
# → Output shows differences in unified diff format

# Сохранение diff в файл для аудита
kubectl diff -f app-config.yaml > changes.diff
```

#### Создание ConfigMap с помощью JSON-Pатча

```bash
# Создание через JSON-Pатч (альтернатива kubectl patch)
kubectl create configmap app-config --dry-run=client -o json | \
  kubectl patch --type merge --patch '{"data":{"LOG_LEVEL":"DEBUG"}}' -f -
```

#### Массовое создание ConfigMap из директории

```bash
# Создание отдельного ConfigMap для каждого подкаталога
for dir in */; do
  if [ -d "$dir/configs" ]; then
    kubectl create configmap "${dir%/}-config" \
      --from-file=./$dir/configs/ \
      --dry-run=client -o yaml | kubectl apply -f -
  fi
done
```
