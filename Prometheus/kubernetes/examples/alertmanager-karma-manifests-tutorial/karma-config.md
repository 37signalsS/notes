# Конфигурация Karma: ConfigMap и настройки UI

## Определения

**ConfigMap конфигурации Karma** — ресурс Kubernetes, содержащий файл `config.yaml`. Karma является stateless-приложением, поэтому все параметры подключения к Alertmanager, правила агрегации и визуализации передаются через этот манифест.

> **См. также:** [Дашборд Karma — общая информация](../../../karma_dashboard.md).

---

## Предварительные требования

Перед созданием ConfigMap убедитесь, что окружение готово:

- Рабочий кластер Kubernetes с правами администратора в namespace `monitoring`.
- Развёрнутый Alertmanager StatefulSet с рабочим ClusterIP Service (`alertmanager.monitoring.svc.cluster.local:9093`).
- Созданный namespace `monitoring` (`kubectl create namespace monitoring`).
- Права на создание ConfigMap в namespace `monitoring`.

---

## Основные концепции

### Статeless-архитектура и внешняя конфигурация

Karma не хранит состояние сессий или персистентные данные на бэкенде. Это упрощает масштабирование и обновление: достаточно изменить ConfigMap и перезапустить поды. Вся логика подключения к источникам, фильтрации и группировки передаётся через `config.yaml`.

### Механизм монтирования

ConfigMap монтируется в под Karma как read-only том. Deployment указывает путь монтирования `/etc/karma`, внутри которого лежит файл `config.yaml`. Аргумент контейнера `--config.file=/etc/karma/config.yaml` явно задаёт расположение конфигурации.

> **Важно:** При изменении содержимого ConfigMap Kubernetes не перезапускает поды автоматически. Для применения новой версии требуется `kubectl rollout restart deployment/karma -n monitoring` или изменение `spec.template` манифеста Deployment (например, через `kubectl apply`).

### Обзор параметров конфигурации

| Секция / параметр | Назначение |
| :--- | :--- |
| `alertmanager.servers` | Список инстансов Alertmanager. `proxy: true` обязателен для создания/редактирования silences через UI. |
| `alertmanager.interval` | Частота опроса серверов Alertmanager. |
| `alertmanager.timeout` | Таймаут запроса к API Alertmanager. |
| `filters.default` | Фильтры, применяемые при загрузке UI (например, `@state=active`). |
| `labels.strip` | Метки, скрываемые в UI для уменьшения шума (служебные метки Kubernetes). |
| `labels.keep` | Важные метки, которые принудительно отображаются в карточке алерта. |
| `grouping.by` | Поля для объединения алертов в группы (по умолчанию `alertname`). |
| `grouping.groupClusterBy` | Дополнительные поля для группировки алертов одного кластера. |
| `disableClusterNameFilter` | Отключает автоматическую фильтрацию по имени кластера в multi-cluster средах. |
| `disableKeepForAlertsWithEmptyLabel` | Скрывать метку, даже если её значение пустое. |
| `readonly` | Режим без возможности создания silences (для TV-панелей). |
| `authentication.oidc` | Настройки OIDC-аутентификации для UI (подробности в SSoT). |
| `acl` | Правила контроля доступа к silences (подробности в SSoT). |

---

## Практические сценарии

### Применение ConfigMap для Karma

**Шаг 1.** Создайте ConfigMap из локального файла или напрямую через манифест.

**Шаг 2.** Проверьте, что ConfigMap создан и содержит ожидаемый ключ.

**Шаг 3.** Убедитесь, что Deployment Karma использует этот ConfigMap.

**Шаг 4.** Проверьте работоспособность UI и лог контейнера на наличие ошибок парсинга конфигурации.

### Манифест ConfigMap для Karma

**`karma-config.yaml`**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: karma-config
  namespace: monitoring
data:
  config.yaml: |
    alertmanager:
      interval: 1m
      timeout: 10s
      servers:
        - name: "Kubernetes Cluster"
          uri: "http://alertmanager.monitoring.svc.cluster.local:9093"
          proxy: true

    filters:
      default:
        - "@state=active"

    labels:
      strip:
        - "receiver"
        - "deployment"
        - "replicaset"
        - "controller-revision-hash"
        - "pod-template-hash"
      keep: ["alertname", "severity", "instance", "pod", "namespace"]

    grouping:
      by: ["alertname", "severity", "namespace"]
      groupClusterBy: ["alertname"]
```

### Применение и первичная валидация

```bash
# Применение манифеста ConfigMap
kubectl apply -f karma-config.yaml

# Проверка создания
kubectl get configmap karma-config -n monitoring -o yaml

# Проверка содержимого ключа config.yaml
kubectl get configmap karma-config -n monitoring -o jsonpath='{.data.config\.yaml}'

# Проверка монтирования в поде Karma
kubectl get pods -n monitoring -l app=karma
kubectl exec -n monitoring <karma-pod> -- cat /etc/karma/config.yaml
# → содержимое должно совпадать с ожидаемым

# Проверка логов на ошибки парсинга конфигурации
kubectl logs -n monitoring <karma-pod> | grep -i "config\|error\|parse"
```

### Перезапуск после изменения ConfigMap

Karma считывает `config.yaml` при старте. После обновления ConfigMap требуется принудительный перезапуск Deployment:

```bash
# Плавный перезапуск пода Karma для подхвата новой конфигурации
kubectl rollout restart deployment/karma -n monitoring

# Ожидание завершения
kubectl rollout status deployment/karma -n monitoring
# → deployment "karma" successfully rolled out

# Проверка ревизии
kubectl rollout history deployment/karma -n monitoring
```

### Валидация изнутри пода

```bash
# Получение имени пода
POD=$(kubectl get pods -n monitoring -l app=karma -o jsonpath='{.items[0].metadata.name}')

# Проверка доступности Alertmanager из пода Karma
kubectl exec -n monitoring $POD -- curl -s http://alertmanager.monitoring.svc.cluster.local:9093/api/v2/alerts
# → [] (если алертов нет) или JSON со списком алертов

# Проверка health endpoint
kubectl exec -n monitoring $POD -- curl -s http://localhost:8080/health
# → {"status":"healthy"}
```

### Устранение неисправностей

| Симптом | Возможная причина | Диагностика и решение |
| :--- | :--- | :--- |
| UI Karma показывает "disconnected" | Неверный `alertmanager.servers.uri` | `kubectl exec -n monitoring <pod> -- curl -s http://alertmanager.monitoring.svc.cluster.local:9093` — проверить доступность изнутри. |
| Кнопка "Silence" неактивна | `proxy: false` или недоступность Alertmanager | Проверить `karma-config.yaml`: `proxy: true` и корректность `uri`. |
| Поля меток не отображаются | Неправильные значения `labels.strip` или `labels.keep` | Проверить точность имён меток в `config.yaml` и сравнить с фактическими метками алертов. |
| Изменения в ConfigMap не применяются | Под не перезапущен после изменения | `kubectl rollout restart deployment/karma -n monitoring`. |
| Ошибка парсинга YAML | Синтаксическая ошибка в `config.yaml` | `kubectl logs -n monitoring <karma-pod> | grep -i parse`; исправить YAML и применить ConfigMap заново. |
| Pod в CrashLoopBackOff | Ошибка в аргументе `--config.file` или правах на том | `kubectl describe pod -n monitoring <karma-pod>`; проверить путь монтирования. |

### Аутентификация через OIDC

Karma поддерживает нативную OIDC-аутентификацию (OpenID Connect) для защиты UI. Это позволяет привязать доступ к корпоративному каталогу (Keycloak, Okta, Azure AD) и не требует дополнительного reverse proxy.

**Блок `authentication.oidc` в `config.yaml`:**

```yaml
authentication:
  oidc:
    issuer: "https://keycloak.example.com/realms/monitoring"
    clientID: "karma"
    clientSecret: "your-client-secret"  # Или через ENV: ${OIDC_CLIENT_SECRET}
    redirectURL: "https://karma.example.com/oidc/callback"
    scopes:
      - openid
      - profile
      - email
      - groups
```

> **Важно:** `clientSecret` не должен храниться в ConfigMap в открытом виде. Используйте `${OIDC_CLIENT_SECRET}` с флагом `--config.expand-external-variables` и Kubernetes Secret (см. [Секреты](./secrets.md)).

**Порядок действий:**

1.  Создайте клиента в Keycloak/Okta с Redirect URI: `https://karma.example.com/oidc/callback`.
2.  Сохраните `clientSecret` в Kubernetes Secret.
3.  Добавьте ENV-переменную в Deployment Karma (см. [Манифест Deployment](./karma-deployment.md)).
4.  Добавьте блок `authentication.oidc` в `karma-config.yaml`.
5.  Примените ConfigMap и перезапустите Karma: `kubectl rollout restart deployment/karma -n monitoring`.

**Проверка:**

```bash
# Откройте UI Karma в браузере → должен произойти редирект на Keycloak/Okta
# После логина → возврат в Karma с отображением алертов
```

### Правила контроля доступа (ACL)

ACL позволяет ограничить, кто может создавать и удалять silences через UI Karma. Правила проверяются по порядку; первое совпадение определяет действие.

**Сценарий 1: Запрет создания silences на production**

```yaml
acl:
  silences:
    - action: block
      filters:
        - cluster=prod
      reason: "Создание тишины на prod-кластере запрещено. Используйте amtool или API Alertmanager."
```

**Сценарий 2: Разрешение только для группы SRE**

```yaml
acl:
  silences:
    - action: allow
      filters:
        - "@author=sre-*"
    - action: block
      reason: "Создание silences разрешено только команде SRE."
```

**Сценарий 3: Комбинированные правила (read-only для staging)**

```yaml
acl:
  silences:
    - action: block
      filters:
        - cluster=staging
      reason: "Staging-кластер доступен только для чтения."
    - action: allow
      filters:
        - cluster=prod
        - "@author=sre-*"
    - action: block
      reason: "По умолчанию создание silences запрещено."
```

> **Важно:** ACL работает только при `proxy: true` в конфигурации сервера Alertmanager. Без этого параметра UI Karma не имеет возможности создавать silences.

### TLS между Karma и Alertmanager

В продакшне соединение между Karma и Alertmanager рекомендуется шифровать через TLS. Karma поддерживает HTTPS для `uri` в конфигурации серверов.

**Шаг 1.** Создайте TLS-сертификат для Alertmanager (или используйте cert-manager):

```bash
# Самоподписанный сертификат (для тестов)
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout alertmanager.key -out alertmanager.crt \
  -subj "/CN=alertmanager.monitoring.svc.cluster.local"

# Создание Secret в Kubernetes
kubectl create secret tls alertmanager-tls \
  --cert=alertmanager.crt --key=alertmanager.key \
  -n monitoring
```

**Шаг 2.** Настройте Alertmanager на использование TLS (через `web.config`):

```yaml
# web.config.yaml (монтируется в Alertmanager)
tls_server_config:
  cert_file: /etc/alertmanager/tls/tls.crt
  key_file: /etc/alertmanager/tls/tls.key
  client_auth_type: RequireAndVerifyClientCert
  client_ca_file: /etc/alertmanager/tls/ca.crt
```

**Шаг 3.** Укажите HTTPS в конфигурации Karma:

```yaml
alertmanager:
  servers:
    - name: "Production"
      uri: "https://alertmanager.monitoring.svc.cluster.local:9093"
      proxy: true
      timeout: 10s
      # Karma использует системный CA-бандл или CA из Secret
      tls:
        ca: /etc/karma/tls/ca.crt
        cert: /etc/karma/tls/client.crt
        key: /etc/karma/tls/client.key
```

> **Примечание:** Поддержка `tls` в `alertmanager.servers` доступна начиная с Karma v0.120+. Для более ранних версий используйте sidecar-прокси или Ingress с mTLS.

### Валидация конфигурации Karma

Перед применением нового `config.yaml` рекомендуется проверить синтаксис:

```bash
# Способ 1: Проверка через логи после перезапуска
kubectl rollout restart deployment/karma -n monitoring
kubectl rollout status deployment/karma -n monitoring
kubectl logs -n monitoring -l app=karma --tail=20 | grep -i "config\|error\|parse"

# Способ 2: Проверка YAML локально
yamllint karma-config.yaml

# Способ 3: Валидация через kubectl (dry-run)
kubectl apply -f karma-config.yaml --dry-run=client
```

### Рекомендации

- **Версионирование:** Храните `karma-config.yaml` в Git-репозитории вместе с остальными манифестами. Это обеспечивает аудит изменений и совместимость с GitOps-процессами.
- **Согласованность имён:** Используйте стабильные имена в `alertmanager.servers[].name`, чтобы не потерять конфигурацию при обновлениях UI.
- **Безопасность:** Для защиты UI Karma используйте OIDC (см. блок `authentication.oidc` выше) или комбинацию Ingress с Basic Auth.
- **Изменения без простоя:** Используйте `kubectl rollout restart` вместо `kubectl delete pod` для применения новой конфигурации. Для автоматизации используйте [Reloader](./karma-deployment.md#reloader-stakater-для-горячей-перезагрузки).
- **Мультикластер:** При подключении нескольких Alertmanager указывайте уникальные `name` для каждого инстанса — это отображается в UI как источник алерта.
- **Чувствительные данные:** Никогда не храните `clientSecret`, пароли и токены в ConfigMap. Используйте `${ENV_VAR}` с Kubernetes Secret.

### Очистка ресурсов

```bash
# Удалить ConfigMap
kubectl delete -f karma-config.yaml

# Удалить Deployment Karma
kubectl delete -f karma-deployment.yaml

# Проверить отсутствие ресурсов
kubectl get configmap,deployment -n monitoring -l app=karma
```

---

## Дополнительная информация

- **[Развёртывание Karma (Deployment)](./karma-deployment.md)** — описание пода, монтирование ConfigMap, ServiceMonitor, PDB, Reloader, HPA.
- **[Сетевой доступ: Сервисы и Ingress](./services.md)** — настройка Ingress Auth для защиты интерфейса Karma.
- **[Дашборд Karma — Безопасность](../../../karma_dashboard.md#безопасность-и-ingress)** — SSoT по защите UI, OIDC и ACL.
- **[Дашборд Karma — Мониторинг](../../../karma_dashboard.md#мониторинг-самой-karma)** — метрики и контроль здоровья.
- **[Сравнение Karma vs Grafana Alerting vs Alertmanager UI](../../../karma_dashboard.md#сравнение-karma-vs-grafana-alerting-vs-alertmanager-ui)** — когда использовать Karma.
