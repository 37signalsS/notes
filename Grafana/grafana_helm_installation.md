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

grafana.ini:
  server:
    root_url: "https://grafana.${STUDENT_ID}.slurm.io" # Замените на ваш домен
```

**Важные замечания по файлу `values`:**
*   **`ingress.hosts` и `grafana.ini.server.root_url`**: Замените `${STUDENT_ID}.slurm.io` на ваш реальный домен или IP-адрес.
*   **`admin.password`**: Используйте сложный и уникальный пароль. В реальных условиях рекомендуется использовать Kubernetes Secret для хранения учетных данных администратора.
*   **`nginx.ingress.kubernetes.io/auth-secret`**: Убедитесь, что секрет с именем `basic-auth-secret` (или другим указанным вами) существует в том же пространстве имен и содержит учетные данные для базовой аутентификации.

### Расширенная конфигурация с `values.yaml` (Провиженинг)

Помимо базовой установки, файл `values.yaml` также является ключевым инструментом для провиженинга Grafana. Это позволяет определять источники данных, дашборды и плагины декларативно, как часть развертывания Helm. Такой подход обеспечивает "Configuration as Code" и упрощает управление Grafana в динамических средах.

Подробнее о провиженинге Grafana см. в документе: [Провиженинг Grafana (Configuration as Code)](./grafana_provisioning.md).

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
