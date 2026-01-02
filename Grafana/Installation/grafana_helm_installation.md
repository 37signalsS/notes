# Установка Grafana в Kubernetes с использованием Helm

Этот документ описывает установку и конфигурацию Grafana в кластере Kubernetes с использованием Helm, следуя структурированному подходу.

## 1. Определения

**Helm-чарт Grafana** — это пакет преднастроенных ресурсов Kubernetes, который позволяет автоматизировать установку, обновление и управление Grafana в кластере.

## 2. Основные концепции

Для эффективной установки Grafana с помощью Helm важно понимать следующие ключевые концепции:

*   **Персистентность (Persistence):** Обеспечивает сохранение данных Grafana (дашборды, источники данных, настройки) между перезапусками подов. Критически важно для продуктивных сред.
*   **Внешний доступ (Ingress):** Настройка Ingress-ресурса для предоставления доступа к веб-интерфейсу Grafana извне кластера.
*   **`root_url`:** Ключевой параметр конфигурации, определяющий публичный URL-адрес Grafana, который используется для генерации корректных ссылок в уведомлениях и интерфейсе.
*   **Provisioning:** Автоматическая загрузка и настройка ресурсов (дашбордов, источников данных) при старте Grafana.
*   **Image Renderer:** Отдельный компонент, позволяющий Grafana создавать изображения графиков для включения в уведомления об алертах.

## 3. Практические сценарии

Ниже представлена пошаговая инструкция по установке и настройке Grafana.

### Шаг 1: Подключение репозитория Helm

Перед установкой необходимо добавить официальный репозиторий Helm-чартов Grafana и обновить его:

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
```

### Шаг 2: Установка и базовая настройка

Установка Grafana производится с помощью команды `helm install`, которая использует файл `values.yaml` для кастомизации.

#### Команда для установки

```bash
helm install grafana grafana/grafana -f grafana-values.yaml --namespace monitoring --create-namespace --wait --atomic
```

*   `grafana`: Имя релиза Helm.
*   `grafana/grafana`: Чарт из добавленного репозитория.
*   `-f grafana-values.yaml`: Путь к файлу с настройками.
*   `--namespace monitoring`: Установка в отдельное пространство имен.
*   `--create-namespace`: Создать пространство имен, если оно не существует.
*   `--wait`: Ожидать завершения всех ресурсов.
*   `--atomic`: Откатить релиз в случае неудачной установки.

#### Пример базовой конфигурации (`grafana-values.yaml`)

Этот файл содержит основные параметры для первого запуска: Ingress, учетные данные администратора, персистентность и `root_url`.

```yaml
ingress:
  enabled: true
  annotations:
    kubernetes.io/ingress.class: nginx
    # Для защиты доступа рекомендуется настроить аутентификацию.
    # Пример с использованием OAuth2 Proxy (необходимо развернуть отдельно):
    # nginx.ingress.kubernetes.io/auth-url: "http://oauth2-proxy.default.svc.cluster.local/oauth2/auth"
    # nginx.ingress.kubernetes.io/auth-signin: "https://sso.your-domain.com/oauth2/start?rd=$request_uri"
  hosts:
    - host: grafana.your-domain.com # Замените на ваш домен
      paths:
        - path: /
          pathType: Prefix
  tls:
    - hosts:
        - grafana.your-domain.com # Замените на ваш домен
      secretName: grafana-tls # Имя секрета TLS
# Секция `ingress` необходима для обеспечения внешнего доступа к Grafana.
# Здесь настраиваются правила маршрутизации, хосты и TLS.
# Аннотации используются для конфигурации Ingress-контроллера (в данном случае, Nginx).

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
    root_url: "https://grafana.your-domain.com" # Замените на ваш домен
```

### Шаг 3: Настройка дополнительных параметров

#### `root_url`

Параметр `root_url` в секции `grafana.ini.server` критически важен для корректной работы Grafana, особенно при генерации ссылок (например, для приглашений пользователей или в уведомлениях об алертах). Если он не задан, Grafana может генерировать некорректные ссылки (например, с `localhost:3000`), что является частой ошибкой при настройке.

```yaml
# values.yaml
grafana.ini:
  server:
    root_url: "https://grafana.your-domain.com" # Укажите полный URL, по которому доступна Grafana
```

#### Provisioned Dashboards (через `sidecar`)

Helm-чарт Grafana позволяет автоматически загружать дашборды при установке, используя механизм `sidecar`. Это удобно для преднастроенных дашбордов, например, из Prometheus Stack.

```yaml
# values.yaml
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

#### Image Renderer

Для прикрепления изображений графиков к уведомлениям об алертах Grafana использует отдельный компонент Image Renderer.

```yaml
# values.yaml
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
*   **Зависимость от Chrome**: Image Renderer использует под капотом headless-браузер для рендеринга изображений.
*   **Особенности для мессенджеров**: Для некоторых мессенджеров (например, Slack) может потребоваться выгрузка изображений во внешнее хранилище (например, S3). Для Telegram в этом нет необходимости.

### Шаг 4: Проверка установки

После выполнения команды `helm install` проверьте статус развертывания:

```bash
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana
kubectl get ingress -n monitoring -l app.kubernetes.io/name=grafana
```

Убедитесь, что все поды Grafana находятся в состоянии `Running` и Ingress-ресурс создан.

### Шаг 5: Доступ к Grafana

После успешного развертывания Grafana будет доступна по адресу, указанному в `ingress.hosts`. Для входа используйте учетные данные администратора, заданные в `values.yaml`.

## 4. Дополнительная информация

Для ознакомления со всеми доступными параметрами конфигурации Helm-чарта Grafana рекомендуется изучить его `values.yaml` по умолчанию.

```bash
helm show values grafana/grafana > grafana-default-values.yaml
```

Эта команда создаст файл `grafana-default-values.yaml` с полным списком опций, комментариями и значениями по умолчанию.