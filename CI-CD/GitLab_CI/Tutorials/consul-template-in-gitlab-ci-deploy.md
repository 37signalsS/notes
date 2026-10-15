**Актуально для:** Consul Template 0.39+ / Vault KV v2 / GitLab 17.0+ (id_tokens)

# Consul Template как рендерер секретов в GitLab CI deploy job

> **Примечание:** устаревшие переменные `CI_JOB_JWT`/`CI_JOB_JWT_V2` были объявлены deprecated
> в GitLab 15.9 и **удалены в GitLab 17.0** — пример ниже использует нативные `id_tokens`.
> Настройка JWT-метода аутентификации в Vault (роль, `bound_audiences`, TTL) — в
> [Интеграция GitLab CI и Vault в Kubernetes](./vault_kubernetes_integration.md).

## Определения

**Consul Template** — бинарник HashiCorp для рендеринга файлов конфигурации из данных
Consul KV, Vault и Nomad. Поддерживает два режима: демон (непрерывный polling + перерисовка)
и one-time (`-once` — однократный рендер и выход).

**Vault KV v2** — версионируемое хранилище секретов. Значения доступны через вложенное поле
`.Data.data.<key>` (структура ответа: `.Data` → `data` + `metadata`).

**GitLab CI deploy job** — задача пайплайна в stage `deploy`, выполняющая выкат на инфраструктуру.

**`id_tokens`** — блок `.gitlab-ci.yml`, генерирующий для задачи краткоживущий подписанный JWT
(ID token) для OIDC-аутентификации во внешних сервисах. Полное описание — в
[Интеграции GitLab CI и Vault в Kubernetes](./vault_kubernetes_integration.md).

**HCL (HashiCorp Configuration Language)** — язык конфигурации для шаблонов consul-template.
Шаблоны используют синтаксис Go templates с функциями `secret` (чтение из Vault), `key` и
`keyOrDefault` (чтение из Consul KV).

## Почему не ESO или Vault Agent?

**ESO (External Secrets Operator)** — на момент настройки проекта недоступен.

**Vault Agent** — подставляет секреты при запуске пода и добавляет sidecar-контейнер к каждому
поду. Подходит для долгоживущих сервисов, но увеличивает сложность и ресурсозатраты.

**Подход с рендерингом на стороне CI** держит кластер «тупым»: Helm-чарт просто использует файлы
из `config/`, без зависимости от Vault во время выполнения подов. Секреты рендерятся в чарт при
деплое и «запекаются» в ConfigMap (для несекретного конфига) или Kubernetes Secret (для
учётных данных).

**Компромисс:** если значение в Vault изменится — требуется перезапуск пайплайна для подхвата
изменений. Для часто ротируемых учётных данных лучше использовать ESO или Vault Agent.

## Архитектура и принцип работы

### Цепочка рендеринга

1. Скачивание Helm-чарта из Artifact registry.
2. Аутентификация в Vault через ID token задачи (`id_tokens`).
3. Рендеринг секретов в директорию чарта (`config/`, `crt/`) через `consul-template -once`.
4. `helm upgrade` — отрендеренные файлы попадают в ConfigMap и Secret внутри кластера.

### Как consul-template находит секрет в KV v2

В HCL-шаблонах ниже путь к секрету указан «без `/data/`» (`Microservices/<service>/<env>/system`),
а значение читается из `.Data.data.<key>` — то есть из KV v2. Обе части согласованы не случайно:

1. Перед чтением consul-template определяет версию mount через эндпоинт
   `sys/internal/ui/mounts/<путь>`.
2. Если mount версии 2, клиент сам вставляет `/data/` в API-путь (функция `shimKVv2Path`
   в `dependency/vault_read.go` исходников consul-template). Путь, уже содержащий `/data/`,
   `/metadata/` или `/subkeys/`, не изменяется.
3. Vault уже принимает запрос по «правильному» пути, а в `.Data` возвращается структура
   `{data: {...}, metadata: {...}}`, откуда шаблон берёт `.Data.data`.

Практические следствия:

- **Политика Vault оценивается по API-пути**, поэтому в политике путь обязан содержать `/data/`,
  даже если шаблон его не содержит (см. [Политика Vault для deploy-роли](#политика-vault-для-deploy-роли)).
- Если consul-template не смог прочитать `sys/internal/ui/mounts/<путь>` (нет прав токена,
  сеть), mount считается KV v1, запрос уходит без `/data/`, данных не приходит — и в режиме
  `-once` процесс висит в ожидании зависимостей (см. [Устранение неполадок](#устранение-неполадок)).

### Структура чарта

```text
my-service/
  Chart.yaml
  values.yaml
  values-Development.yaml
  values-Production.yaml
  config/
    appsettings.json        # consul-template HCL — рендерится при деплое
    appsettings.ENV.json    # переопределения для конкретной среды
  crt/
    YC-CA.pem               # рендерится из Vault
  files/
    config.hcl              # исходный consul-template шаблон для appsettings.json
    config-user.hcl         # шаблон переопределений для среды
    config-crt.hcl          # шаблон CA-сертификата
  templates/
    configmap.yaml
    deployment.yaml
    ...
```

Файлы в `config/` и `crt/` — результат рендеринга: их нет в git, они создаются через
`consul-template -once` в CI job и затем встраиваются в ConfigMap через `helm upgrade`.

## Предварительные требования

**Инструменты в образе задачи.** Пример использует образ
`registry.example.com/ci-images/vault-cli:1.0.1`, в котором уже есть все необходимые бинарники:

| Инструмент | Назначение | Проверка |
|---|---|---|
| `consul-template` 0.39+ | рендер конфигов из Vault/Consul | `consul-template -version` |
| Vault CLI | обмен ID token на Vault-токен, чтение kubeconfig | `vault version` |
| Helm 3 | скачивание чарта и выкат | `helm version --short` |

**Доступ и настройки:**

- раннер должен достучаться до Vault (`VAULT_ADDR`), до Artifact registry и до Kubernetes API;
- в Vault настроен JWT auth method и роль `access-<env>` для групп/проектов GitLab, её
  `bound_audiences` совпадает с `aud` ID token, а политика даёт `read` только на нужные пути
  секретов — пошаговая настройка в
  [Интеграции GitLab CI и Vault в Kubernetes](./vault_kubernetes_integration.md);
- файлы `config/`, `crt/` исключены из git (`.gitignore`), а для прохождения `helm lint` и
  локального `helm template` в репозитории лежат заглушки (например `{}` для `appsettings.json`) —
  см. [Сценарий 5](../../../Kubernetes/ToolsUtilities/Helm/templating/scenarios/config-rendering-pattern.md#сценарий-5-helm-lint-с-заглушками-для-gitignore-файлов);

**Переменные deploy job:**

| Переменная | Пример | Назначение |
|---|---|---|
| `VAULT_ADDR` | `https://vault.example.com` | адрес Vault для Vault CLI и consul-template |
| `APP_ENV` | `Production` | среда: выбирает `values-<env>.yaml` и ветку секретов |
| `CHART_NAME` | `my-service` | имя чарта в registry и рабочая директория после `helm fetch` |
| `NAMESPACE` | `app` | namespace в целевом кластере |
| `INSTANCE` | `my-service-prod` | имя Helm-релиза |
| `VAULT_ID_TOKEN` | — | генерируется GitLab из блока `id_tokens`, вручную не задаётся |

## Практические сценарии

### HCL-шаблоны

`files/config.hcl` читает из Vault KV v2 и рендерит корректный JSON:

```go-template
{{ with $env := env "APP_ENV" }}
{{ $prj := "my-service" }}
{
  "ConnectionStrings": {
    "DefaultConnection": "{{ $path := printf "Microservices/%s/%s/system" $prj $env }}{{ with secret $path }}{{ .Data.data.connection_string }}{{ end }}"
  },
  "RabbitMq": {
    "Host":     "{{ with secret (printf "common-secret/%s/" $env) }}{{ .Data.data.rabbit_hostname }}{{ end }}",
    "Port":     "{{ with secret (printf "common-secret/%s/" $env) }}{{ .Data.data.rabbit_port }}{{ end }}",
    "Username": "{{ with secret (printf "common-secret/%s/" $env) }}{{ .Data.data.rabbit_username }}{{ end }}",
    "Password": "{{ with secret (printf "common-secret/%s/" $env) }}{{ .Data.data.rabbit_password }}{{ end }}"
  },
  "Logging": {
    "MinimumLevel": {
      {{- if eq $env "Production" }}
      "Default": "Warning"
      {{- else }}
      "Default": "Debug"
      {{- end }}
    }
  }
}
{{ end }}
```

Два паттерна путей Vault:

- `Microservices/<service>/<env>/system` — секреты конкретного сервиса (URL базы, API-ключи).
- `common-secret/<env>/` — общая инфраструктура (RabbitMQ, Elastic, эндпоинт APM).

`files/config-user.hcl` выгружает весь KV-секрет `user` как форматированный JSON:

```go-template
{{ with $env := env "APP_ENV" }}
{{ $prj := "my-service" }}
{{ $path := printf "Microservices/%s/%s/user" $prj $env }}{{ with secret $path }}{{ .Data.data | toJSONPretty }}{{ end }}
{{ end }}
```

`files/config-crt.hcl` достаёт YC root CA из общего пути Vault:

```go-template
{{ with $env := env "APP_ENV" }}
{{ with secret (printf "common-secret/%s/" $env) }}{{ .Data.data.yc_ca }}{{ end }}
{{ end }}
```

### Политика Vault для deploy-роли

Минимальные права роли, которой пользуется deploy job. Путь в политике — это API-путь Vault,
поэтому для KV v2 mount он содержит `/data/`, хотя HCL-шаблон его не содержит:

```hcl
# секреты сервиса: system- и user-секреты среды
path "Microservices/data/my-service/Production/system" {
  capabilities = ["read"]
}
path "Microservices/data/my-service/Production/user" {
  capabilities = ["read"]
}

# общий инфраструктурный секрет окружения целиком (RabbitMQ, kubeconfig и т.д.)
path "common-secret/data/Production" {
  capabilities = ["read"]
}
path "common-secret/data/Production/*" {
  capabilities = ["read"]
}
```

Проверка прав выданного токена:

```bash
vault token capabilities Microservices/data/my-service/Production/system
# → read
```

Подробности синтаксиса политик и capabilities — в [Авторизации в Vault](../../../Vault/authorization.md).

### Deploy job

```yaml
.deploy:
  image: registry.example.com/ci-images/vault-cli:1.0.1
  stage: deploy
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.example.com
  script:
    # 1. Скачать чарт из Helm registry
    - helm repo add charts https://artifacts.example.com/repository/helm/
    - helm repo update
    - helm fetch charts/${CHART_NAME} --untar

    # 2. Аутентификация в Vault через ID token задачи
    - export VAULT_TOKEN="$(vault write -field=token auth/jwt/login
        role=access-${APP_ENV} jwt=$VAULT_ID_TOKEN)"
    - vault kv get -field=kubeconfig_${NAMESPACE} common-secret/${APP_ENV} > kube_config
    - chmod 600 kube_config

    # 3. Рендеринг секретов в директорию чарта
    - consul-template -template="${CHART_NAME}/files/config-crt.hcl:${CHART_NAME}/crt/YC-CA.pem" -once
    - consul-template -template="${CHART_NAME}/files/config-user.hcl:${CHART_NAME}/config/appsettings.ENV.json" -once
    - consul-template -template="${CHART_NAME}/files/config.hcl:${CHART_NAME}/config/appsettings.json" -once

    # 4. Деплой с отрендеренными файлами в chart/config/
    - helm upgrade --install --wait \
        --kubeconfig kube_config \
        ${INSTANCE} ${CHART_NAME} \
        -f ${CHART_NAME}/values-${APP_ENV}.yaml \
        -n ${NAMESPACE} \
        --set aspnetcoreEnvironment=${APP_ENV} \
        --set image.tag=${CI_COMMIT_SHORT_SHA}
  after_script:
    - rm -f kube_config
```

`after_script` выполняется в отдельном шелле — убирать переменные там не требуется: `VAULT_TOKEN`
и `VAULT_ID_TOKEN` не покидают задачу. Удаляется только файл `kube_config`, который иначе
останется в рабочей директории shell-executor.

Флаг `-template src:dst` принимает HCL-источник и пишет отрендеренный результат по пути назначения.
Его можно повторять несколько раз в одном вызове — тогда один процесс отрендерит все файлы
(один снимок секретов вместо трёх независимых чтений):

```bash
consul-template \
  -template="${CHART_NAME}/files/config-crt.hcl:${CHART_NAME}/crt/YC-CA.pem" \
  -template="${CHART_NAME}/files/config-user.hcl:${CHART_NAME}/config/appsettings.ENV.json" \
  -template="${CHART_NAME}/files/config.hcl:${CHART_NAME}/config/appsettings.json" \
  -once
```

В deploy job выше оставлены три отдельных вызова. Если значение ротируется между вызовами,
файлы получат разные версии секрета, поэтому предпочитайте один общий вызов.

Vault-токен consul-template читает из переменной `$VAULT_TOKEN` автоматически
(порядок приоритета: `vault_agent_token_file` → `token` в конфигурации → переменная окружения
`VAULT_TOKEN`).

### Как чарт забирает отрендеренные файлы

Читает `.Files.Get` и передаёт через `tpl`: ConfigMap подхватывает `config/appsettings.json`
и `config/appsettings.ENV.json`, отдельный ConfigMap — `crt/YC-CA.pem` (монтируется в
`/etc/ssl/certs/`). Разбор шаблонов, нюансы `indent`/`nindent`, монтирование через `subPath` и
stub-файлы для `helm lint` — в
[Управлении конфигурацией через Files.Get, tpl и директорию config/](../../../Kubernetes/ToolsUtilities/Helm/templating/scenarios/config-rendering-pattern.md).

### Rolling update при изменении конфига

В `spec.template.metadata.annotations` Deployment добавляются контрольные суммы ConfigMap
(`checksum/configmap: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}`).
Когда пайплайн заново рендерит `config/appsettings.json`, меняется содержимое ConfigMap, за ним —
хеш аннотации шаблона пода, и Kubernetes запускает rolling restart. Без этой аннотации
`helm upgrade` обновил бы ConfigMap, а работающие поды продолжили бы держать старый конфиг.
Подробный разбор паттерна — в [Автоматическом перезапуске подов](../../../Kubernetes/ToolsUtilities/Helm/templating/scenarios/restart_on_change.md);
отдельно о проблеме необновляемых файлов при `subPath` — в
[Сценарии 2 config-rendering-pattern](../../../Kubernetes/ToolsUtilities/Helm/templating/scenarios/config-rendering-pattern.md#сценарий-2-subpath-volumemounts-в-deployment).

### Валидация

Проверки по шагам — от локального рендеринга до состояния в кластере:

```bash
# 1. Рендер в stdout вместо записи на диск (флаг -dry)
consul-template -template="files/config.hcl:/tmp/appsettings.json" -dry -log-level=debug

# 2. После рендеринга в job: файлы не пустые
test -s ${CHART_NAME}/config/appsettings.json
# → exit 0

# 3. Чарт валиден с отрендеренными файлами
helm lint ${CHART_NAME} -f ${CHART_NAME}/values-${APP_ENV}.yaml
# → 1 chart(s) linted, 0 chart(s) failed

# 4. Токен жив и имеет нужные политики
vault token lookup
# → policies: [default access-Production]
```

После `helm upgrade` (имя ConfigMap по шаблону чарта — `<fullname>-app-settings`):

```bash
# 5. ConfigMap в кластере содержит отрендеренный конфиг
kubectl get configmap <fullname>-app-settings -n ${NAMESPACE} \
  -o jsonpath='{.data.appsettings\.json}'

# 6. Аннотация контрольной суммы в шаблоне пода изменилась, деплой завершён
kubectl rollout status deployment/${INSTANCE} -n ${NAMESPACE} --timeout=5m
kubectl get deployment ${INSTANCE} -n ${NAMESPACE} \
  -o jsonpath='{.spec.template.metadata.annotations.checksum/configmap}'
```

## Устранение неполадок

### Локальная отладка рендеринга

```bash
export VAULT_ADDR=https://vault.test.example.com
export VAULT_TOKEN=<ваш-dev-токен>
export APP_ENV=Development

consul-template -template="files/config.hcl:/tmp/appsettings.json" -once -log-level=debug
cat /tmp/appsettings.json
```

Если consul-template зависает (не завершается с `-once`) — путь к секрету не существует либо
mount не определён как KV v2: блок `{{ with secret }}` ждёт данных бесконечно (в `-once` режиме
процесс ждёт отрисовки всех зависимостей). Проверьте путь в Vault:

```bash
vault kv get Microservices/my-service/Development/system
# → выводит содержимое KV v2 секрета с версией и метаданными
```

### Типичные ошибки

| Симптом | Причина | Диагностика и решение |
|---|---|---|
| `consul-template -once` висит и не завершается | секрета по пути нет, или consul-template посчитал mount KV v1 (не смог прочитать `sys/internal/ui/mounts/<путь>`) и читает путь без `/data/` | `vault kv get <путь>`; `vault secrets list -detailed` — у mount должен быть `options=map[version:2]`; `-log-level=debug` покажет предупреждение `failed to check if ... is KVv2`, `-log-level=trace` — фактический запрос `GET /v1/<путь>` |
| Ошибка `403` / `permission denied` при чтении | у токена нет `read` на API-путь (в KV v2 — с `/data/`) | `vault policy read <политика>`; `vault token capabilities <api-путь>` → должен быть `read` |
| Пустой файл назначения при ненулевом коде выхода | Vault недоступен, токен истёк или права минимальны | `vault status`, `vault token lookup`; проверить `VAULT_ADDR` и сеть от раннера до Vault |
| Рендер прошёл, но под работает со старым конфигом | нет `checksum/*`-аннотации в Deployment, либо файл смонтирован через `subPath` и не обновляется kubelet'ом | см. [Rolling update при изменении конфига](#rolling-update-при-изменении-конфига) и [config-rendering-pattern](../../../Kubernetes/ToolsUtilities/Helm/templating/scenarios/config-rendering-pattern.md) |
| `helm lint` / `helm template` падает: файл конфига не найден | `config/*` в `.gitignore` и нет stub-файла | добавьте заглушку `{}` (см. [Предварительные требования](#предварительные-требования)) |
| Отрендеренные секреты попали в git | рендеринг запущен вне CI или файл не в `.gitignore` | `git status` в репозитории; откатить коммит и добавить путь в `.gitignore` |

## Ограничения

- Если значение в Vault изменилось без нового деплоя — поды держат старое значение до
  следующего запуска пайплайна. Для часто ротируемых учётных данных лучше использовать External
  Secrets Operator или Vault Agent.
- Отрендеренный `config/appsettings.json` никогда не попадает в git — он существует только во
  временной файловой системе CI-раннера во время deploy job.
- `consul-template -once` завершается с ненулевым кодом, если Vault недоступен или у токена нет
  прав. Так и задумано: `helm upgrade` не запустится с неполным конфигом.
- Доступность Vault становится обязательным условием деплоя: сеть от раннера до Vault — часть
  критического пути поставки.

## Очистка

- `after_script` задачи удаляет `kube_config`. Переменные окружения (`VAULT_TOKEN`,
  `VAULT_ID_TOKEN`) не переходят между задачами — каждая job выполняется в новом шелле
  (и в новом контейнере при docker-executor), поэтому сбрасывать их не нужно. Удалять файл
  важно на shell-executor: рабочая директория раннера сохраняется между запусками.
- Отрендеренные `config/` и `crt/` остаются в workspace до конца job; артефакты (`artifacts:`)
  на них настраивать не нужно — секреты не должны покидать задачу.
- Helm хранит отрендеренный манифест (включая содержимое ConfigMap и Secret чарта) в Secret
  релиза `sh.helm.release.v1.<release>.v<N>` того же namespace — доступ на чтение Secret в
  namespace даёт доступ к этим данным. `helm uninstall` удаляет секреты релиза,
  `--keep-history` сохраняет их; подробнее — в [Версионировании Helm-релизов](../../../Kubernetes/ToolsUtilities/Helm/helm_release_versioning.md).
- Отзыв учётной записи CI: `vault token revoke -accessor <accessor>`; массовый отзыв сессий
  роли — в разделе очистки
  [Интеграции GitLab CI и Vault](./vault_kubernetes_integration.md#очистка-и-откат-cleanup).

## Лучшие практики

- Рендеринг на стороне CI устраняет runtime-зависимость подов от Vault, но требует перезапуска
  пайплайна для применения изменений секретов. Оценивайте trade-off против ESO/Vault Agent.
- Используйте `sha256sum`-аннотации для принудительного rolling restart при изменении ConfigMap.
- Не коммитьте отрендеренные файлы из `config/` и `crt/` в git — они являются артефактами сборки.
- Ограничивайте права Vault-токена минимумом привилегий: `read` только на нужные API-пути
  (для KV v2 — с `/data/`, см. [Политика Vault для deploy-роли](#политика-vault-для-deploy-роли)).
- Аутентифицируйте pipeline через OIDC/`id_tokens` вместо устаревшего `CI_JOB_JWT`.
- Рендерите все шаблоны одним вызовом `consul-template` — тогда все файлы получают согласованный
  снимок секретов (см. [Deploy job](#deploy-job)).
- Секреты не передавайте через `--set` и не кладите в `values*.yaml`: значения попадают в логи
  CI, в `helm history` и в `helm get values` — см.
  [Helm-секреты](../../../Kubernetes/Base/secrets/helm_secrets.md).
- Учётные данные размещайте в Kubernetes Secret, ConfigMap — только для несекретного конфига;
  проверяйте, что у ConfigMap с секретами нет случайного RBAC-доступа «на чтение всем».

## Дополнительная информация

- **[Vault Agent — базовая конфигурация](../../../Vault/guides/vault_agent/basics.md)** — шаблоны Vault Agent на базе Consul Template (daemon-режим, авто-ротация секретов).
- **[Интеграция GitLab CI и Vault в Kubernetes](./vault_kubernetes_integration.md)** — OIDC/`id_tokens`, VSO, ротация секретов через runtime.
- **[Управление секретами в CI/CD](../../DevSecOps/secrets_management.md)** — модели получения секретов, жизненный цикл, реагирование на инциденты.
- **[KV Store Consul](../../../Consul/consul_kv_store.md)** — использование consul-template с Consul KV (отличное от Vault KV).
- **[Nginx как обратный прокси для Consul](../../../WebServers/Nginx/Scenarios/nginx_as_reverse_proxy_for_consul.md)** — другой сценарий consul-template: динамический upstream из Consul catalog.
- **[Официальная документация: Consul Template](https://developer.hashicorp.com/consul/docs/automate/consul-template)** — режимы (`-once`), синтаксис шаблонов.
- **[Официальная документация: Vault KV v2](https://developer.hashicorp.com/vault/docs/secrets/kv)** — структура ответа `.Data.data`.
