# Установка Grafana с использованием Helm

Этот документ описывает пошаговую установку и базовую конфигурацию Grafana в кластере Kubernetes с использованием Helm. Мы рассмотрим подключение репозитория Helm, настройку файла `values.yaml` для Ingress, базовой аутентификации, персистентности и учетных данных администратора, а также процесс установки и проверки.

## Подключение репозитория Helm

Перед установкой Grafana необходимо добавить официальный репозиторий Helm-чартов Grafana:

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
```

## Установка Grafana

Перед установкой Grafana рекомендуется ознакомиться с доступными параметрами конфигурации по умолчанию, используя команду `helm show values`:

```bash
helm show values grafana/grafana > grafana-default-values.yaml
```

Это позволит вам увидеть все опции, которые можно переопределить в вашем файле `values.yaml`.

Установка Grafana производится с использованием Helm и файла `values.yaml`, который содержит все необходимые настройки. Пример команды для установки:

```bash
helm install grafana grafana/grafana -f grafana-values-1.yaml --namespace monitoring --create-namespace --wait --atomic
```

Здесь:
*   `grafana` — имя релиза Helm.
*   `grafana/grafana` — указывает на чарт Grafana из добавленного репозитория.
*   `-f grafana-values-1.yaml` — путь к файлу с пользовательскими значениями конфигурации.
*   `--namespace monitoring` — установка в пространство имен `monitoring`.
*   `--create-namespace` — создает пространство имен, если оно не существует.
*   `--wait` — ожидает завершения всех ресурсов перед тем, как пометить релиз как успешный.
*   `--atomic` — если установка не удалась, релиз будет автоматически откачен.

## Настройка файла values (grafana-values-1.yaml)

Пример содержимого файла `grafana-values-1.yaml` для базовой настройки:

```yaml
ingress:
  enabled: true
  annotations:
    kubernetes.io/ingress.class: nginx
    nginx.ingress.kubernetes.io/auth-url: "http://kube-auth.default.svc.cluster.local/auth" # Пример, замените на ваш URL
    nginx.ingress.kubernetes.io/auth-signin: "https://${STUDENT_ID}.slurm.io/oauth2/start?rd=$request_uri" # Пример, замените на ваш URL
    nginx.ingress.kubernetes.io/auth-type: basic
    nginx.ingress.kubernetes.io/auth-secret: basic-auth-secret # Имя секрета с учетными данными для базовой аутентификации
  hosts:
    - host: grafana.${STUDENT_ID}.slurm.io # Замените на ваш домен
      paths:
        - path: /
          pathType: Prefix
  tls:
    - hosts:
        - grafana.${STUDENT_ID}.slurm.io # Замените на ваш домен
      secretName: grafana-tls # Имя секрета TLS
# Секция `ingress` необходима для обеспечения внешнего доступа к Grafana.
# Здесь настраиваются правила маршрутизации, хосты и, при необходимости, базовая аутентификация
# для защиты доступа к веб-интерфейсу Grafana.
# Аннотации `nginx.ingress.kubernetes.io/auth-*` используются для настройки базовой авторизации
# через Ingress-контроллер Nginx.
admin:
  user: admin
  password: admin.12.3 # Используйте надежный пароль и храните его в секрете!

persistence:
  enabled: true
  type: pvc
  size: 5Gi
# Секция `persistence` позволяет сохранять данные Grafana (например, дашборды, источники данных,
# настройки пользователей) между перезапусками подов. Это критически важно для сохранения
# состояния Grafana и предотвращения потери данных при переразвертывании или сбоях.
# `enabled: true` активирует использование PersistentVolumeClaim (PVC) для хранения данных.
# Grafana использует внутреннюю базу данных (по умолчанию SQLite) для хранения истории алертов,
# настроек и информации о пользователях. Настройка персистентного хранилища предотвращает потерю этих данных.

grafana.ini:
  server:
    root_url: "https://grafana.${STUDENT_ID}.slurm.io" # Замените на ваш домен

## Дополнительные параметры конфигурации

При установке Grafana через Helm, помимо основных настроек, можно задать ряд дополнительных параметров, которые влияют на ее поведение и функциональность.

### `root_url`

Параметр `root_url` в секции `grafana.ini.server` критически важен для корректной работы Grafana, особенно при генерации ссылок (например, для приглашений пользователей или в уведомлениях об алертах). Если он не задан, Grafana может генерировать некорректные ссылки (например, с `localhost:3000`), что является частой ошибкой при настройке.

```yaml
grafana:
  ini:
    server:
      root_url: "https://grafana.your-domain.com" # Укажите полный URL, по которому доступна Grafana
```

### Provisioned Dashboards (через `sidecar`)

Helm-чарт Grafana позволяет автоматически загружать дашборды при установке, используя механизм `sidecar` или напрямую указывая их в `values.yaml`. Это один из способов получить готовые графики сразу после инсталляции, не создавая их вручную. Это удобно для преднастроенных дашбордов, например, из Prometheus Stack.

```yaml
grafana:
  sidecar:
    dashboards:
      enabled: true
      label: grafana_dashboard
      labelValue: "1"
      folder: /var/lib/grafana/dashboards
      provider:
        name: default
        folder: ''
        type: file
        disableDeletion: false
        editable: true
```
*   **`enabled: true`**: Включает механизм sidecar для дашбордов.
*   **`label` и `labelValue`**: Используются для поиска ConfigMaps или Secrets, содержащих JSON-определения дашбордов.
*   **`editable: true/false`**: Определяет, можно ли редактировать эти дашборды через UI Grafana. Часто provisioned дашборды делают `read-only`. Параметр `disableDeletion` (по умолчанию `false`) позволяет предотвратить удаление дашбордов через UI.

### Image Renderer

Для прикрепления изображений графиков к уведомлениям об алертах (например, в Slack) Grafana использует отдельный компонент Image Renderer. Его также можно включить и настроить через `values.yaml`.

```yaml
grafana:
  imageRenderer:
    enabled: true
    # Дополнительные настройки, например, для S3, если требуется внешнее хранилище для изображений
    # s3:
    #   bucket: "grafana-alert-images"
    #   region: "us-east-1"
    #   accessKey: "${VAULT_KEY_AWS_ACCESS_KEY}"
    #   secretKey: "${VAULT_KEY_AWS_SECRET_KEY}"
```
*   **`enabled: true`**: Включает Image Renderer.
*   **Зависимость от Chrome**: Image Renderer использует под капотом headless-браузер (например, Google Chrome) для рендеринга изображений. Если изображения не прикрепляются к алертам, убедитесь, что под с Image Renderer запущен и корректно настроен.
*   **Особенности для мессенджеров**: Для некоторых мессенджеров (например, Slack) может потребоваться выгрузка изображений во внешнее хранилище (например, S3), так как API мессенджера требует, чтобы изображение уже где-то хостилось. Для других, как Telegram, в этом нет необходимости, и изображение можно отправить напрямую.

## Проверка установки

После выполнения команды `helm install` можно проверить статус развертывания:

```bash
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana
kubectl get ingress -n monitoring -l app.kubernetes.io/name=grafana
```

Убедитесь, что все поды Grafana находятся в состоянии `Running` и Ingress-ресурс создан.

## Доступ к Grafana

После успешного развертывания Grafana будет доступна по адресу, указанному в `ingress.hosts`. При первом доступе потребуется ввести учетные данные для базовой аутентификации (если настроено), а затем учетные данные администратора Grafana:

*   **Логин:** `admin`
*   **Пароль:** `admin.12.3` (или тот, который вы указали в `values.yaml`)

После входа вы попадете в интерфейс Grafana. На этом этапе Grafana установлена, но еще не имеет источников данных или дашбордов.
