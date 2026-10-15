# Управление конфигурацией через Files.Get, tpl и директорию config/

**Актуально для:** Helm 3.14+

---

## Определения

**.Files.Get** — встроенная функция Helm, считывающая содержимое статического файла из корня чарта (включая директории `files/`, `config/`, `crt/` и т.п.) и возвращающая его как строку. Файлы из `templates/` недоступны через `.Files`.

**tpl** — функция Helm, обрабатывающая строку как шаблон Go templates. Позволяет использовать `{{ .Values.* }}` внутри внешних файлов, загруженных через `.Files.Get`.

**consul-template** — шаблонизатор HashiCorp, который извлекает данные из Consul KV и Vault и рендерит конфигурационные файлы. Часто используется в CI/CD для подстановки секретов до упаковки чарта.

**subPath** — директива `volumeMounts`, монтирующая один ключ ConfigMap или Secret как отдельный файл по точечному пути, не затрагивая остальное содержимое директории.

**ENV placeholder** — шаблонное имя файла (`appsettings.ENV.json`), в котором буквальная строка `ENV` сохраняется как есть и заменяется на окружение (Production, Development и т.д.) на этапе рендеринга через `{{ .Values.aspnetcoreEnvironment }}`.

---

## Базовые концепции

### Проблема values.yaml для конфигурации

Типичный соблазн — положить конфигурацию приложения в `values.yaml`:

```yaml
# Так не делать
config:
  connectionString: "Server=db;Database=app;User=app;Password=secret"
  rabbitHost: "rabbit.infra"
```

Затем в шаблоне:

```yaml
data:
  appsettings.json: |
    {
      "ConnectionStrings": { "Default": "{{ .Values.config.connectionString }}" },
      "RabbitMq": { "Host": "{{ .Values.config.rabbitHost }}" }
    }
```

**Проблемы подхода:**

1. **Раздутый values.yaml:** для умеренно сложного сервиса накапливается 40+ ключей.
2. **Многострочные значения в YAML:** отступы, escape-последовательности и кавычки становятся источником ошибок.
3. **Отсутствие логики в values:** внутри `values.yaml` нельзя использовать условия (`if eq $env "Production"`).
4. **Секреты в открытом виде:** `values-Production.yaml` может содержать сырые пароли.

### Паттерн Files.Get + tpl + config/

Вместо встраивания конфигурации в `values.yaml`, конфиг хранится как нормальный файл (JSON, YAML) внутри директории `config/` чарта. Шаблоны рендерятся во время CI с помощью consul-template, а затем упаковываются в ConfigMap через `Files.Get` и `tpl`.

```text
my-service/
  config/
    appsettings.json         ← рендерится consul-template при деплое
    appsettings.ENV.json     ← переопределения для среды, тоже рендерятся
  crt/
    YC-CA.pem                ← CA-сертификат, рендерится из Vault
  files/
    config.hcl               ← источник consul-template для appsettings.json
    config-user.hcl          ← источник для appsettings.ENV.json
    config-crt.hcl           ← источник для YC-CA.pem
```

Шаблон ConfigMap загружает отрендеренные файлы через `Files.Get`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "my-service.fullname" . }}-app-settings
data:
  appsettings.json: |
{{ tpl (.Files.Get "config/appsettings.json") . | indent 4 }}
  appsettings.{{ .Values.aspnetcoreEnvironment }}.json: |
{{ tpl (.Files.Get "config/appsettings.ENV.json") . | indent 4 }}
```

Обратите внимание на `tpl` вокруг `.Files.Get`: содержимое файла проходит через движок шаблонов Helm, и внутри JSON-файла можно ссылаться на `{{ .Values.* }}`. Это удобно для подстановки `{{ .Values.replicaCount }}` или `{{ .Release.Namespace }}` в конфиг.

### Почему indent 4, а не nindent 4

Функция `indent 4` добавляет 4 пробела к каждой строке. Функция `nindent 4` добавляет ведущий перенос строки и затем 4 пробела. Для многострочного block scalar (|) в YAML правильно использовать `indent` — первая строка должна начинаться с того же отступа, что и остальные.

С `nindent` в начале значения появляется лишняя пустая строка — для большинства парсеров она безвредна, но выглядит некрасиво в `kubectl get cm -o yaml`.

```yaml
# indent 4 — корректный вариант для block scalar при выражении в колонке 0
  appsettings.json: |
{{ tpl (.Files.Get "config/appsettings.json") . | indent 4 }}

# nindent 4 — добавляет пустую строку после |
  appsettings.json: |
{{ tpl (.Files.Get "config/appsettings.json") . | nindent 4 }}
```

---

## Практические сценарии

### Сценарий 1: Отдельный ConfigMap с CA-сертификатом

CA PEM выделяется в отдельный ConfigMap, чтобы его можно было обновлять независимо от основной конфигурации:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "my-service.fullname" . }}-ca-pemstore
data:
  YC-CA.pem: |
{{ .Files.Get "crt/YC-CA.pem" | indent 4 }}
```

Здесь `tpl` не нужен — PEM это просто текст, а не шаблон.

### Сценарий 2: subPath volumeMounts в Deployment

Два ConfigMap монтируются в контейнер по точным путям, которые ожидает .NET runtime:

```yaml
volumeMounts:
  - name: config
    mountPath: /app/appsettings.json
    subPath: appsettings.json
  - name: config
    mountPath: /app/appsettings.{{ .Values.aspnetcoreEnvironment }}.json
    subPath: appsettings.{{ .Values.aspnetcoreEnvironment }}.json
  - name: ca-pemstore
    mountPath: /etc/ssl/certs/YC-CA.pem
    subPath: YC-CA.pem
    readOnly: true

volumes:
  - name: config
    configMap:
      name: {{ include "my-service.fullname" . }}-app-settings
  - name: ca-pemstore
    configMap:
      name: {{ include "my-service.fullname" . }}-ca-pemstore
```

`subPath` монтирует один ключ из ConfigMap как файл, не заменяя всю директорию. Без `subPath` монтирование в `/app` скрыло бы все остальные файлы в этой директории.

> **Важно:** Файлы, смонтированные через `subPath`, не обновляются автоматически Kubelet при изменении ConfigMap, так как создаётся bind mount на конкретный inode. Поэтому паттерн rolling restart через checksum-аннотации (см. ниже) становится обязательным. Подробнее о механизме и ограничениях `subPath` — в [Pod Usage: монтирование ConfigMap](../../../../Base/ConfigMap/pod_usage.md).

### Сценарий 3: Принудительный rolling restart при изменении конфига

В `.spec.template.metadata.annotations` Deployment хранится хеш каждого ConfigMap:

```yaml
# templates/deployment.yaml (фрагмент)
metadata:
  annotations:
    checksum/configmap: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
    checksum/configmap-ca: {{ include (print $.Template.BasePath "/capem-configmap.yaml") . | sha256sum }}
```

**Как это работает:**

1. `include (print $.Template.BasePath "/configmap.yaml") .` рендерит шаблон ConfigMap в строку.
2. `sha256sum` хеширует её.
3. Хеш сохраняется в аннотации Pod template.
4. Когда секреты в Vault меняются и пайплайн заново рендерит `config/appsettings.json`, меняется содержимое ConfigMap, за ним — хеш и спецификация Pod template, и Kubernetes автоматически запускает rolling update.

Без этой аннотации `helm upgrade` обновил бы ConfigMap, но существующие поды продолжили бы работать со старым конфигом: Kubernetes не перезапускает поды при изменении примонтированного ConfigMap, а файлы, смонтированные через `subPath`, не обновляются автоматически вовсе.

### Сценарий 4: CI-рендеринг секретов через consul-template

Имя файла `appsettings.ENV.json` содержит буквальную строку `ENV` — и в git, и в пути назначения consul-template:

```bash
# consul-template рендерит appsettings.json из Vault, ENV остаётся как есть
consul-template \
  -template="chart/files/config.hcl:chart/config/appsettings.json" \
  -template="chart/files/config-user.hcl:chart/config/appsettings.ENV.json" \
  -template="chart/files/config-crt.hcl:chart/crt/YC-CA.pem" \
  -once
```

Значение `aspnetcoreEnvironment` (Development, Production и т.д.) передаётся при деплое через `--set aspnetcoreEnvironment=${APP_ENV}`. Шаблон `configmap.yaml` использует `{{ .Values.aspnetcoreEnvironment }}` для именования ключа, так что в рантайме контейнер получает `/app/appsettings.Production.json`.

### Сценарий 5: helm lint с заглушками для gitignore-файлов

Поскольку `config/appsettings.json` добавлен в `.gitignore` (это артефакт рендеринга consul-template), нужен файл-заглушка, чтобы `helm lint` проходил:

```json
{}
```

Закоммитьте эту заглушку как `config/appsettings.json` — `consul-template` перезапишет её при деплое. `helm lint` и локальные вызовы `helm template` увидят пустой, но корректный JSON-объект.

---

## Операции и команды

| Команда | Назначение |
|---------|-----------|
| `consul-template -template="src:dst" -once` | Рендеринг конфигурационных файлов из Vault в CI |
| `helm template <release> ./chart -f values.yaml` | Локальный рендеринг для проверки без кластера |
| `helm lint ./chart` | Валидация структуры и синтаксиса |
| `include (print $.Template.BasePath "/configmap.yaml") . \| sha256sum` | Вычисление хеша содержимого ConfigMap для checksum-аннотации |
| `kubectl rollout status deployment/<name> --timeout=5m` | Ожидание завершения Rolling Update |

---

## Устранение неисправностей

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `file not found` при `.Files.Get` | Файл в `templates/` или попадает под `.helmignore` | Переместите файл в корень чарта или проверьте `.helmignore` |
| Лишняя пустая строка после `\|` в ConfigMap | Использован `nindent` вместо `indent` для block scalar | Используйте `indent 4` (см. [Почему indent 4, а не nindent 4](#почему-indent-4-а-не-nindent-4)) |
| Под не перезапускается после изменения ConfigMap | `subPath` блокирует автообновление, а checksum-аннотация отсутствует | Добавьте `checksum/configmap` в `spec.template.metadata.annotations` |
| `helm lint` падает с `file not found` | Конфиг-файлы в `.gitignore` | Добавьте stub-файлы (например, `{}` для JSON) |
| Хеш не меняется при `helm upgrade` | Файл попадает в `.helmignore` или не пересобран consul-template | Проверьте, что CI заново рендерит конфиг перед `helm package` |

---

## Лучшие практики

1. **Чистый конфиг в config/:** храните JSON/YAML конфиги как обычные файлы в `config/`, а не встроенные в `values.yaml` многострочные блоки.
2. **Секреты через consul-template + Vault:** рендерите секреты в CI из Vault до `helm package`, чтобы они не попадали в git в открытом виде.
3. **Отдельные ConfigMaps:** выносите CA-сертификаты и другие часто обновляемые файлы в отдельные ConfigMap с собственными checksum-аннотациями.
4. **subPath для точек монтировки:** используйте `subPath` для монтирования отдельных файлов в ожидаемые пути (.NET runtime), но помните о необходимости checksum-аннотации для обновления.
5. **Stub-файлы для lint:** закоммиченные заглушки для gitignore-артефактов обеспечивают проходимость `helm lint` и локального `helm template`.
6. **ENV placeholder:** используйте буквальную строку `ENV` в именах файлов конфигурации, чтобы consul-template и Helm обрабатывали их одинаково.
7. **indent для block scalar:** используйте `indent N` (а не `nindent`) при оформлении block scalar `|` в ConfigMap, когда выражение шаблона начинается в колонке 0.

---

## Дополнительная информация

- [ConfigMap и внешние файлы](./configmap_files.md) — методы инъекции данных через объект `.Files`, работа с бинарными данными, массовый импорт.
- [Автоматический перезапуск подов](./restart_on_change.md) — подробный разбор checksum-аннотаций, `sha256sum`, `include` и `tpl` для Rolling Update.
- [Обзор сценариев шаблонизации](./overview.md) — руководство по выбору сценария для типовых задач.
- [Монтирование ConfigMap в под](../../../../Base/ConfigMap/pod_usage.md) — механизмы `subPath`, projected volumes, Hot Reload.
- [Best practices ConfigMap](../../../../Base/ConfigMap/best_practices.md) — хеширование имен, управление lifecycle.
