# Автоматический перезапуск подов (Restart on Change)

---

## Определения

**Checksum-аннотации (аннотации контрольной суммы)** — специальные метаданные, размещаемые в секции `spec.template.metadata.annotations` контроллеров Kubernetes (Deployment, StatefulSet, DaemonSet). Они содержат криптографический хеш (SHA-256) отрендеренного содержимого конфигурационных файлов (ConfigMap или Secret). Изменение этого хеша при обновлении чарта вынуждает Kubernetes запустить процесс плавного обновления (Rolling Update) для применения новых настроек.

---

## Основные концепции

### Принцип работы

1. В спецификацию шаблона пода (`spec.template`) добавляется аннотация, имя которой обычно начинается с `checksum/` (например, `checksum/config`).
2. В качестве значения аннотации вычисляется хеш-сумма от содержимого файлов конфигурации с помощью функций Helm.
3. При выполнении команд `helm upgrade`, `helm install` или `helm rollback` Helm заново рендерит все шаблоны. Если данные в ConfigMap или Secret изменились по сравнению с текущим состоянием в кластере (или при переходе между ревизиями), итоговая строка хеша также изменится.
4. Kubernetes отслеживает изменения в `spec.template`. Любое изменение в этой секции (включая только аннотации) приводит к созданию новой ревизии ReplicaSet (для Deployment) и инициации Rolling Update.

### Почему это необходимо

Kubernetes обладает специфическим поведением при обновлении внешних конфигураций:
- **Переменные окружения (`env`, `envFrom`):** Значения считываются только в момент старта контейнера. Если ConfigMap в API обновится, переменные в уже запущенном поде останутся старыми до ручного перезапуска.
- **Тома (`volumes`):** Изменения в ConfigMap/Secret синхронизируются на файловую систему пода через `kubelet` с задержкой (по умолчанию до 1-2 минут). Однако большинство приложений считывают конфиг один раз при старте и не отслеживают изменения файлов (отсутствие механизма Hot Reload через `inotify`).

Использование паттерна "Restart on Change" гарантирует, что приложение всегда работает с актуальной конфигурацией, так как обновление настроек автоматически влечет за собой контролируемый перезапуск всех экземпляров приложения.

### Ключевые функции Helm

| Функция | Назначение в контексте паттерна |
| :--- | :--- |
| `print` | Формирует полный путь к файлу шаблона внутри чарта для функции `include`. |
| `include` | Рендерит указанный шаблон и возвращает результат как строку, что позволяет передавать его в пайплайн. |
| `sha256sum` | Генерирует SHA-256 отпечаток. Использование SHA-256 предпочтительнее `sha1sum` из-за более высокой устойчивости к коллизиям. |
| `tpl` | Позволяет обработать строку как полноценный шаблон Helm (необходимо для динамических конфигов). |
| `toYaml` | Преобразует структуру данных (Map/List) в YAML-строку для последующего хеширования. |

---

## Практические сценарии

### Deployment с ConfigMap

Использование глобального контекста `$` позволяет корректно вычислять пути даже внутри вложенных циклов (`range`).

**templates/configmap.yaml:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-config
data:
  app.conf: |
    server_port: {{ .Values.server.port | default 8080 }}
    log_level: {{ .Values.logging.level | default "info" }}
```

**templates/deployment.yaml:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      app: {{ include "myapp.name" . }}
  template:
    metadata:
      annotations:
        # Автоматический перезапуск при изменении configmap.yaml
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
    spec:
      containers:
        - name: app
          image: {{ .Values.image.repository }}:{{ .Values.image.tag }}
          volumeMounts:
            - name: config-volume
              mountPath: /etc/app
      volumes:
        - name: config-volume
          configMap:
            name: {{ include "myapp.fullname" . }}-config
```

### StatefulSet и DaemonSet

Для этих контроллеров механизм идентичен — аннотация должна находиться строго внутри `spec.template.metadata`. Это инициирует обновление подов согласно `updateStrategy` (например, `RollingUpdate` или `OnDelete`).

**templates/daemonset.yaml:**
```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: {{ include "myapp.fullname" . }}-agent
spec:
  template:
    metadata:
      annotations:
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
    spec:
      containers:
        - name: agent
          image: {{ .Values.agent.image }}
          volumeMounts:
            - name: config
              mountPath: /etc/agent
      volumes:
        - name: config
          configMap:
            name: {{ include "myapp.fullname" . }}-config
```

### Сценарий с Secret (Обновление паролей)

При хешировании секретов важно помнить, что хеш будет храниться в открытом виде в аннотациях Deployment. Хотя это необратимый хеш, само наличие изменений в секрете становится видимым в манифесте пода.

**templates/secret.yaml:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "myapp.fullname" . }}-secret
type: Opaque
data:
  db-password: {{ .Values.db.password | b64enc | quote }}
```

**templates/deployment.yaml (фрагмент):**
```yaml
spec:
  template:
    metadata:
      annotations:
        # Хешируется отрендеренный YAML секрета
        checksum/secret: {{ include (print $.Template.BasePath "/secret.yaml") . | sha256sum }}
```

### Динамические файлы и каталоги (Files.Glob)

Если ConfigMap собирается из множества файлов в папке (например, `configs/`), необходимо вычислить суммарный хеш, учитывающий и пути, и содержимое.

```yaml
annotations:
  # Хеширование всех файлов в папке configs для отслеживания любых изменений
  checksum/all-configs: {{ range $path, $bytes := $.Files.Glob "configs/**" }}{{ $path }}{{ $bytes | sha256sum }}{{ end | sha256sum }}
```

### Хеширование объектов из Values

Если конфигурация передается непосредственно в `values.yaml` в виде объекта, можно использовать `toYaml` для получения стабильного строкового представления перед хешированием.

```yaml
annotations:
  # Хеширование всего блока параметров из values.yaml
  checksum/params: {{ .Values.appConfig | toYaml | sha256sum }}
```

---

## Разбор работы аннотации

Рассмотрим подробно цепочку обработки:

```yaml
checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
```

1. **`$.Template.BasePath`**: Системная переменная, возвращающая путь к директории `templates` чарта. Использование префикса `$` гарантирует доступ к глобальной области видимости.
2. **`print`**: Формирует полную строку пути к файлу.
3. **`include`**: Выполняет рендеринг файла как именованного шаблона. Это критично, так как мы хотим отслеживать изменения именно в *результате* рендеринга (с учетом подставленных значений `values`), а не в исходном файле.
4. **`sha256sum`**: Генерирует контрольную сумму от полученной строки. Если хотя бы один символ в ConfigMap изменится, изменится и весь хеш.

---

## Тонкости и нюансы

### Влияние пробелов и форматирования

Функция `sha256sum` чувствительна к любым изменениям байтов.
- Добавление пустой строки или изменение отступа в ConfigMap изменит хеш.
- Добавление комментария в YAML-файл, который не попадает в итоговый `data` объекта ConfigMap, но присутствует в шаблоне, также изменит хеш при использовании `include`.

### include против template

Это фундаментальное различие:
- **`template`**: Директива, которая просто вставляет контент. Она не возвращает значение, поэтому её нельзя использовать в пайплайне после символа `|`.
- **`include`**: Функция, возвращающая строку. Только её можно комбинировать с `sha256sum`.

### Обработка динамических шаблонов (tpl)

Если файлы конфигурации считываются через `.Files.Get` и содержат внутри себя теги Helm (например, `{{ .Release.Name }}`), обычного чтения недостаточно. Нужно прогнать их через функцию `tpl`:

```yaml
# 1. Считываем файл
# 2. Рендерим его как шаблон (tpl)
# 3. Считаем хеш от результата
checksum/config: {{ tpl ($.Files.Get "configs/app.conf") . | sha256sum }}
```

---

## Проверка и отладка

### Использование helm-diff

Для проверки того, изменится ли хеш (и, как следствие, произойдет ли перезапуск) перед деплоем, рекомендуется использовать плагин `helm-diff`:

```bash
helm diff upgrade my-release ./my-chart --values values.yaml
```
В выводе будет четко видно изменение значения в секции `annotations`.

### Интроспекция через kubectl

Проверка текущего значения хеша в работающем кластере:

```bash
kubectl get deploy my-app -o jsonpath='{.spec.template.metadata.annotations.checksum/config}'
```

---

## Ограничения и риски

- **Статическая природа**: Паттерн работает только в момент рендеринга Helm. Он "не видит" изменений, сделанных напрямую в кластере (например, через `kubectl edit configmap`) или изменений внешних секретов (Vault, AWS Secrets Manager).
- **Лимит аннотаций**: Kubernetes имеет ограничение на размер аннотаций (256KB). Хеширование очень больших структур данных не вызовет проблем (хеш всегда короткий), но сам рендеринг `include` может замедлить работу Helm на гигантских файлах.
- **Ложные срабатывания**: Использование функций с побочными эффектами (`now`, `randAlphaNum`) внутри хешируемых файлов приведет к тому, что хеш будет меняться при *каждом* запуске `helm upgrade`, вызывая ненужные перезапуски подов.
- **Rollback**: При выполнении `helm rollback` Helm восстановит состояние аннотаций из выбранной ревизии, что также инициирует перезапуск подов для возврата к старой конфигурации.

---

## Дополнительная информация

- [Функции Helm](../functions.md) — детальный разбор `sha256sum`, `tpl` и `include`.
- [Обновление и Rollout ConfigMap](../../../../Base/ConfigMap/update_and_rollout.md) — как Kubernetes обрабатывает изменения конфигурации на уровне Kubelet.
- [stakater/Reloader](../../../reloader/reloader_overview.md) — альтернативный "динамический" подход к перезапуску через контроллер.
- [Kustomize Name Hashing](../../../../ToolsUtilities/kustomize/kustomize_advanced_features.md) — аналогичный механизм в Kustomize через суффиксы имен ресурсов.
