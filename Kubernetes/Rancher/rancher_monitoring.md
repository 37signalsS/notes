# Мониторинг в Rancher

## Определения

**Rancher Monitoring (Cluster Monitoring / Global Monitoring)** — интегрированное решение для развертывания и управления полным стеком наблюдаемости (observability), базирующееся на **Prometheus Operator**. Пакет представляет собой адаптированную версию Helm-чарта `kube-prometheus-stack`, оптимизированную для мультикластерной среды Rancher. В UI Rancher этот уровень называется **Cluster Monitoring** и обеспечивает мониторинг всей инфраструктуры кластера.

**Rancher Project Monitoring (Project Monitoring v2)** — уровень мониторинга, изолированный по проектам (Projects). Реализуется компонентом **Prometheus Federator** (оператор, основанный на `rancher/helm-project-operator`), который автоматически развертывает отдельный стек мониторинга (Prometheus + Alertmanager + Grafana) для каждого проекта по запросу владельца проекта. Позволяет независимо собирать метрики приложений в рамках проекта, не затрагивая глобальный (кластерный) Prometheus.

**Prometheus v3.x (2026)** — текущее поколение сервера мониторинга, поддерживающее нативный прием данных по протоколу OTLP (OpenTelemetry), высокую производительность TSDB и улучшенное управление памятью.

**Grafana Alloy** — универсальный агент (наследник Grafana Agent), который в современных инсталляциях Rancher (v2.10+) может использоваться совместно с Prometheus Operator для унифицированного сбора метрик, логов и трассировок.

**AlertmanagerConfig** — ресурс Kubernetes (CRD) для декларативного управления маршрутизацией алертов. Позволяет делегировать настройку уведомлений владельцам проектов (Projects) без предоставления доступа к глобальному Alertmanager.

## Базовые концепции

### Двухуровневая модель мониторинга

Мониторинг в Rancher разделен на два логических уровня, которые дополняют друг друга:

| Уровень | Компонент | Область охвата | Кто управляет |
| :--- | :--- | :--- | :--- |
| **Cluster Monitoring** | `rancher-monitoring` | Весь кластер (инфраструктура: kubelet, etcd, API Server, узлы) | Cluster Admins |
| **Project Monitoring** | `prometheus-federator` → `rancher-project-monitoring` | Один проект (нагрузки приложений в namespace проекта) | Project Owners / Members |

Такое разделение обеспечивает **изоляцию данных и RBAC**: владельцы проектов не видят метрики инфраструктуры и других проектов, а администраторы кластера не засоряют глобальный Prometheus метриками конкретных приложений.

### Архитектура и компоненты 2026 года

Пакет `rancher-monitoring` является форком/адаптацией upstream-чарта `kube-prometheus-stack` и обеспечивает глубокую интеграцию компонентов мониторинга с ресурсами кластера.

1.  **Prometheus Server**:
    *   **Server Mode**: хранение данных в локальном TSDB. Рекомендуется для Management-кластера или небольших Downstream-кластеров.
    *   **Agent Mode (v2)**: только сбор и пересылка данных (Remote Write / OTLP) во внешние хранилища (VictoriaMetrics, Mimir). В 2026 году является стандартом для крупных продуктивных сред.
2.  **Grafana Unified Alerting**: интеграция, позволяющая управлять всеми оповещениями (Prometheus, Loki, Tempo) из единого интерфейса Grafana с привязкой к RBAC Rancher.
3.  **OpenTelemetry Integration**: поддержка сбора метрик напрямую через OTLP без использования промежуточных экспортеров.

Помимо собственно Prometheus, Alertmanager и Grafana, чарт развертывает стандартные экспортеры и вспомогательные компоненты:

*   **`kube-state-metrics`** — метрики состояния объектов Kubernetes (Deployment, ReplicaSet, Pod, Node, PVC и др.), необходимые для дашбордов.
*   **`prometheus-node-exporter`** — метрики узлов (CPU, память, диск, сеть).
*   **`prometheus-adapter`** (опционально) — реализация Custom Metrics API / Metrics API для HPA (Horizontal Pod Autoscaler).
*   **Grafana Dashboards и PrometheusRules** — предустановленные дашборды и правила алертов, синхронизированные из `kube-prometheus` и Prometheus Operator.

### Версионирование чарта и соответствие upstream

Пакет `rancher-monitoring` использует двухчастную схему версий **`<rancher-версия>+up<upstream-версия>`**, где `rancher-версия` — номер сборки Rancher, а `upstream-версия` — версия исходного `kube-prometheus-stack`, на которой основан чарт.

| Rancher | Пример версии чарта | Upstream база |
| :--- | :--- | :--- |
| v2.11 | `106.x+up66.7.1`, `106.x+up69.8` | kube-prometheus-stack 66/69 |
| v2.14 | `109.x+up80.9.1` | kube-prometheus-stack 80.9 |

> **Практическое следствие:** при проверке версий важно смотреть именно на `upstream-версию` после `+up`, поскольку она определяет возможности (поддержку OTLP, новых CRD, версии Prometheus/Grafana). Пакетная версия `rancher-версия` лишь отражает порядок сборок для конкретного релиза Rancher.

### Namespace и селекторы (Release Label)

По умолчанию `rancher-monitoring` устанавливается в namespace **`cattle-monitoring-system`**. `nameOverride` чарта равен `rancher-monitoring`, поэтому все прометеусовские селекторы по умолчанию настроены на метку:

```
release: "rancher-monitoring"
```

Это означает, что для того, чтобы **Prometheus обнаружил ваш `ServiceMonitor`/`PodMonitor`/`PrometheusRule`/`AlertmanagerConfig`**, ресурс должен нести метку `release: rancher-monitoring`. Без неё ресурс будет проигнорирован оператором. (Подробнее о механизме селекторов — в разделе **Практические сценарии** ниже и в SSoT ресурсах Prometheus Operator.)

Также в системную поставку входит namespace `cattle-dashboards`, куда деплоятся дашборды Grafana.

### Особенности интеграции Rancher

*   **Мультикластерная агрегация**: возможность настройки Remote Write для всех кластеров в единый "Monitoring Hub". Детали и настройка Remote Read/Write — в [Remote Read / Remote Write](../../Prometheus/scaling/remote_read_write.md).
*   **RBAC & Projects**: Rancher автоматически настраивает права доступа к дашбордам Grafana на основе членства пользователя в проектах (Projects).
*   **Автоматизация etcd**: встроенные механизмы безопасного скрейпинга etcd для дистрибутивов RKE2 и K3s (при включенном `etcd-expose-metrics` на уровне кластера).
*   **Интеграция с авторизацией Rancher**: доступ к Grafana и Alertmanager UI настраивается через RBAC Rancher (Global/Cluster/Project роли), а не через отдельную аутентификацию Grafana.
*   **Требования к ресурсам**: стандартный стек Rancher Monitoring для кластера обычного размера ожидает около **4 ГБ RAM** (Prometheus — основной потребитель). Учитывайте это при планировании ресурсов узлов.

### Архитектура Project Monitoring (Prometheus Federator)

Prometheus Federator управляется через CRD **`ProjectHelmChart`** с `spec.helmApiVersion: monitoring.cattle.io/v1alpha1` (в UI Rancher — "Project Monitors"). Используются три типа namespace:

| Тип namespace | Имя | Назначение |
| :--- | :--- | :--- |
| **Operator / System** | `cattle-monitoring-system` | Логи оператора, продолжающиеся Helm-релизы всех проектных стеков. Только Cluster Admins. |
| **Project Registration** | `cattle-project-<projectID>` | Наблюдается оператором за CR `ProjectHelmChart`; RBAC здесь — источник прав для Release namespace. |
| **Project Release** | `cattle-project-<projectID>-monitoring` | Размещает развернутый проектный стек (Prometheus + Alertmanager + Grafana). |

На каждую команду `ProjectHelmChart` оператор:
1.  Автоматически создает **`HelmChart` CR** (управляет `helm install/upgrade/uninstall`) и **`HelmRelease` CR** (фиксирует Helm-релиз, защищает от дрейфа ресурсов).
2.  Развертывает проектный стек в Release namespace.
3.  Автоматически назначает RBAC в Release namespace на основе ролей (`admin`/`edit`/`view`) владельцев проекта из Registration namespace — так пользователи получают доступ только к своему проектному мониторингу.

Каждый проектный стек по умолчанию **федерирует (federate)** namespace-scoped-метрики из кластерного Prometheus, поэтому дашборды приложений работают без установки дополнительных экспортеров.

## Практические сценарии

### Включение мониторинга (Cluster Monitoring) через Apps & Marketplace

Мониторинг кластера включается в Rancher через **Apps & Marketplace** (установка Helm-чарта `rancher-monitoring`).

**Предварительные требования:**
*   Rancher Server v2.5+ (рекомендуются актуальные v2.11/v2.14).
*   Наличие StorageClass / PV для постоянного хранения метрик (Prometheus TSDB и Grafana).
*   Достаточно ресурсов на узлах (минимум ~4 ГБ RAM под стек).

**Шаги:**
1.  В Web UI откройте кластер → **Apps → Charts**.
2.  Найдите чарт **Rancher Monitoring** (устанавливается из системного каталога).
3.  На шаге конфигурации задайте параметры (см. `values.yaml` ниже).
4.  Нажмите **Install**, дождитесь статуса `Deployed`.

```yaml
# values.yaml — минимальная настройка для установки по умолчанию
prometheus:
  prometheusSpec:
    storageSpec:               # постоянное хранилище TSDB
      volumeClaimTemplate:
        spec:
          storageClassName: standard
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 50Gi
    retention: 15d             # срок хранения метрик в локальном TSDB
grafana:
  persistence:
    enabled: true              # постоянство дашбордов/настроек Grafana
    storageClassName: standard
    accessModes: ["ReadWriteOnce"]
    size: 10Gi
  service:
    type: ClusterIP
```

**Объяснение ключевых параметров:**
*   `prometheus.prometheusSpec.storageSpec` — PVC для TSDB; без него все метрики теряются при перезапуске пода Prometheus.
*   `prometheus.prometheusSpec.retention` — период хранения данных (в `d`/`h`/`w`); для экономии диска используйте Agent Mode с Remote Write (`retention: 24h`).
*   `grafana.persistence` — постоянство дашбордов и настроек Grafana (важно, т.к. чарт использует `deploymentStrategy: Recreate` при подключении PV).
*   `grafana.service.type` — по умолчанию `ClusterIP` (доступ через порт-форвардинг); при необходимости опубликуйте через Ingress/LoadBalancer.

**Проверка установки:**

```bash
# Статус Helm-релиза
helm -n cattle-monitoring-system status rancher-monitoring

# Все поды стека должны быть Running/Ready
kubectl -n cattle-monitoring-system get pods
# → prometheus-rancher-monitoring-prometheus-0   2/2     Running
# → alertmanager-rancher-monitoring-alertmanager-0  2/2  Running
# → grafana-<hash>                               1/1     Running
```

### Доступ к Grafana и аутентификация

По умолчанию Grafana недоступна извне (ClusterIP). Типовые способы доступа:

**1. Через Rancher UI (рекомендуется):** В Rancher Web UI откройте кластер → **Monitoring**, оттуда ссылка на Grafana. Авторизация выполняется через RBAC Rancher (пользователь получает доступ на основе своей проектной роли), отдельные учётные данные Grafana не требуются.

**2. Временный порт-форвардинг (для администратора):**

```bash
# Форвардинг порта Grafana на локальную машину
kubectl -n cattle-monitoring-system port-forward svc/<grafana-svc> 3000:80
# → Открыть http://localhost:3000
```

**3. Постоянная публикация через Ingress (production):**

```yaml
# values.yaml — публикация Grafana через Ingress
grafana:
  ingress:
    enabled: true
    hosts: ["grafana.example.com"]
    tls:
      - hosts: ["grafana.example.com"]
        secretName: grafana-tls
```

> **Важно по безопасности:** не включайте базовую аутентификацию Grafana (`admin/admin`), если доступ уже ограничен RBAC Rancher через ingress/аннотации — это создает второй, неконтролируемый путь входа. Используйте один механизм аутентификации (Rancher RBAC) и ограничьте сетевой доступ к Grafana.

### Сбор метрик приложения через ServiceMonitor

Это стандартный метод интеграции пользовательских приложений в мониторинг. Полная теория и все параметры `ServiceMonitor` (селекторы, relabeling, интервалы) — в SSoT [ServiceMonitor (CRD)](../../Prometheus/kubernetes/operator/crd/servicemonitor.md). Ниже приведен адаптированный под `rancher-monitoring` пример.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: app-monitor
  namespace: prod-app
  labels:
    release: rancher-monitoring # Метка обязательна для обнаружения оператором
spec:
  selector:
    matchLabels:
      app: my-app
  endpoints:
  - port: web
    interval: 30s
    path: /metrics
```

**Критическая деталь:** для `Cluster Monitoring` селектор `serviceMonitorSelector` настроен на `release: rancher-monitoring`, поэтому метка `release: rancher-monitoring` на `ServiceMonitor` **обязательна**, иначе цель не появится в Prometheus. Если проектный мониторинг (Federator) активен, такие ресурсы автоматически игнорируются проектными стеками.

Если приложение не имеет Kubernetes Service (например, sidecar-метрики), используйте `PodMonitor` — см. [PodMonitor (CRD)](../../Prometheus/kubernetes/operator/crd/podmonitor.md). Для blackbox-проверок внешних сервисов — [Probe (CRD)](../../Prometheus/kubernetes/operator/crd/probe.md).

### Изоляция алертов через AlertmanagerConfig

Пример настройки уведомлений в Telegram для конкретной команды разработчиков (Namespace-scoped). Полный справочник параметров и тонкости (пустой селектор, агрегация маршрутов) — в [AlertmanagerConfig (CRD)](../../Prometheus/kubernetes/operator/crd/alertmanagerconfig.md).

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: AlertmanagerConfig
metadata:
  name: team-alerts
  namespace: prod-app
  labels:
    release: rancher-monitoring
spec:
  route:
    receiver: 'telegram-receiver'
    groupBy: ['alertname', 'severity']
  receivers:
  - name: 'telegram-receiver'
    telegramConfigs:
    - botToken:
        name: telegram-secret
        key: token
      chatID: -100123456789
```

Правила алертов (какие метрики считать проблемой) задаются отдельно ресурсом `PrometheusRule` — см. [PrometheusRule (CRD)](../../Prometheus/kubernetes/operator/crd/prometheusrule.md). Взаимодействие определений `PrometheusRule` → маршрутов `AlertmanagerConfig` → получателей образует полный конвейер оповещения.

### Настройка Agent Mode v2 с Remote Write

Для минимизации потребления ресурсов в Downstream-кластере настройте Prometheus в режиме агента через `values.yaml` (или UI). Детальная теория агрегации метрик между кластерами — в [Remote Read / Remote Write](../../Prometheus/scaling/remote_read_write.md).

```yaml
prometheus:
  prometheusSpec:
    enableFeatures:
      - agent
      - otlp-receiver # Включение нативной поддержки OTLP (v3+)
    remoteWrite:
      - url: "https://mimir.example.com/api/v1/push"
        basicAuth:
          username:
            name: mimir-creds
            key: user
          password:
            name: mimir-creds
            key: password
```

### Включение Project Monitoring (Prometheus Federator)

**Шаги:**
1.  Установите **Rancher Monitoring** (`rancher-monitoring`) в кластере — Prometheus Federator требует уже развернутого Prometheus Operator.
2.  В **Apps & Marketplace** установите чарт **Prometheus Federator**.
3.  Важно: поместите namespace **`cattle-monitoring-system` в System Project** (или в другой изолированный проект), а также существенно увеличьте CPU/память кластерного Prometheus (проектные стеки федерируют метрики через него, см. «Проверка установки» для типового размера).
4.  В кластере перейдите в **Monitoring → Project Monitors** и создайте Project Monitor для нужного проекта.

```bash
# Проверка, что оператор Federator стартовал и захватил лок
kubectl -n cattle-monitoring-system logs deploy/prometheus-federator | grep -i "leader\|acquired"
# → Leader election acquired lock
```

После включения в Release namespace проекта появится проектный стек:

```bash
kubectl -n cattle-project-<id>-monitoring get pods
```

**Рекомендация по селекторам:** для безопасности и изоляции установите на `rancher-monitoring` селекторы так, чтобы кластерный Prometheus наблюдал **только** ресурсы меткой `release: rancher-monitoring` (это соответствует дефолту, но стоит явно перепроверить после обновлений), тогда проектные стеки не будут «перетягивать» чужие метрики.

## Диагностика и устранение неполадок

### Цели (Targets) не появляются в Prometheus

1.  **Проверьте метку селектора:** `ServiceMonitor`/`PodMonitor` должен иметь `release: rancher-monitoring` (совпадать с `serviceMonitorSelector`/`podMonitorSelector`).
2.  **Проверьте, что оператор вообще видит ресурс:** в UI Prometheus → Status → Targets. Метрика отсутствует — значит, ресурс не подобран.
3.  **Логи Prometheus Operator:**

```bash
kubectl -n cattle-monitoring-system logs -l app.kubernetes.io/name=prometheus-operator --tail=50
# → ищите "failed to generate config" или предупреждения о селекторах
```

4.  **Имя порта:** `port` в `ServiceMonitor` должен совпадать с **именем** (name) или номером порта в `Service`.

### Prometheus перезапускается с OOMKilled

*   **Симптом:** под `prometheus-<name>-0` в `CrashLoopBackOff` / OOMKilled; дашборды пустые.
*   **Причина:** недостаточно памяти при высокой кардинальности метрик (особенно при активном Project Monitoring и федерировании).
*   **Решение:** увеличьте limits/requests памяти кластерного Prometheus; используйте Agent Mode с Remote Write; добавляйте проектным стекам больше памяти, если включен Federator.

```bash
# Текущее потребление памяти прометеуса (из метрик)
kubectl -n cattle-monitoring-system exec -it prometheus-rancher-monitoring-prometheus-0 -- \
  sh -c 'stress_equal=1; wget -qO- http://localhost:9090/api/v1/status/runtimeinfo | grep memory'
```

### Данные теряются после перезапуска пода

*   **Причина:** не настроен `storageSpec` (нет PVC), либо PVC удалена.
*   **Решение:** задайте `prometheus.prometheusSpec.storageSpec` с `volumeClaimTemplate` до установки; проверьте `kubectl -n cattle-monitoring-system get pvc`.
*   **Edge case:** чарт использует `deploymentStrategy: Recreate` для Grafana при подключенном PV — старый под удаляется до создания нового; учитывайте это при обновлениях.

### Проблемы при включении Project Monitoring (Federator)

| Симптом | Возможная причина | Решение |
| :--- | :--- | :--- |
| Project Monitor создан, стек не появился | Оператор не захватил лок / нет прав | Проверить логи `prometheus-federator`; убедиться, что `cattle-monitoring-system` в System Project. |
| Пользователь не видит свой проектный мониторинг | RBAC не назначен автоматически | Проверить роль (`admin`/`edit`/`view`) в Registration namespace проекта. |
| Кластерный Prometheus перегружен | Проекты федерируют много метрик | Увеличить память; ограничить селекторы `release: rancher-monitoring`. |

### Алерты не приходят

1.  Проверьте, что `PrometheusRule` несет метку `release: rancher-monitoring` (подбирается `ruleSelector`).
2.  Проверьте, что `AlertmanagerConfig` несет ту же метку и что `alertmanagerConfigSelector` не пустой (`{}`).
3.  Проверьте через UI Alertmanager (Status → Configuration), видит ли он ваш маршрут.
4.  Проверьте наличие Secret с токеном (например, `telegram-secret`) в том же namespace.

### Удаление мониторинга (Cleanup)

```bash
# Удаление Helm-релиза (данные TSDB при этом могут остаться в PVC)
kubectl delete App -n cattle-monitoring-system rancher-monitoring

# При необходимости удалить CRD (осторожно! удаляет все CustomResources мониторинга)
# kubectl delete crd $(kubectl get crd | grep monitoring.coreos.com | awk '{print $1}')
```

> **Предупреждение:** удаление CRD необратимо удаляет все `ServiceMonitor`, `PrometheusRule`, `AlertmanagerConfig`, `PodMonitor`, `Probe`, а также данные. Выполняйте только после уверенного вывода из эксплуатации.

## Дополнительная информация

### Статус компонентов и версионность (2026)

| Компонент | Версия | Статус | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Prometheus Operator** | v0.89+ | Актуально | Полная поддержка OTLP и ScrapeConfigs |
| **Prometheus** | v3.x | Stable | Использовать OTLP для новых приложений |
| **Grafana** | v13.x | Актуально | Основной интерфейс Unified Alerting |

> Уточнение: версии компонентов внутри `rancher-monitoring` определяются **upstream-версией** после `+up`. Для Rancher 2.14 (upstream 80.9) стек соответствует актуальным релизам Prometheus 3.x и Grafana 13.x.

### Рекомендации по масштабированию

*   **Sharding**: используйте `spec.shards` в ресурсе Prometheus для горизонтального масштабирования сбора метрик в сверхкрупных кластерах (1000+ узлов).
*   **Alloy Collector**: для гибридных задач (метрики + логи + профилирование) внедряйте Grafana Alloy вместо набора разрозненных экспортеров — см. [Grafana Alloy: обзор](../../Grafana/grafana_alloy_overview.md).
*   **Cardinality Management**: регулярно анализируйте "тяжелые" метрики через дашборд "Prometheus Stats" и применяйте `metricRelabelConfigs` для удаления неиспользуемых лейблов.
*   **Проектный мониторинг вместо одного гигантского Prometheus**: для больших кластеров со множеством команд включайте Project Monitoring (Federator), чтобы изолировать нагрузку и права.
*   **Agent Mode**: в крупных средах используйте Prometheus Agent с Remote Write в центральное хранилище и сократите `retention` до миллисекунд/часов (данные хранятся в агрегаторе).

### Рекомендации по безопасности

*   **Namespace мониторинга**: держите `cattle-monitoring-system` в изолированном проекте (System Project) с ограниченным доступом (только Cluster Admins) — предотвращает эскалацию через exec в поды оператора/Helm Jobs.
*   **Селекторы**: ограничьте кластерный Prometheus только ресурсами `release: rancher-monitoring`, чтобы избежать непреднамеренного сбора чужих метрик и SSRF через ServiceMonitor (см. [безопасность оператора](../../Prometheus/kubernetes/operator/Security/access_control.md)).
*   **Секреты в конфигах**: токены ботов/алиасы храните в Kubernetes Secrets, а не в открытом виде в `values.yaml` — см. [секреты и лучшие практики](../../Prometheus/kubernetes/operator/Security/secrets_best_practices.md).
*   **Ingress**: не открывайте Grafana/Alertmanager без ограничения доступа; пользуйтесь RBAC Rancher и не включайте параллельно встроенную аутентификацию Grafana.

### Типовые конфигурации для Production

**V1: Классическая (Server Mode + Retention):** Prometheus Server с локальным TSDB, `retention` 15–30 дней, Grafana с Persistence. Подходит для небольших и средних кластеров.

**V2: Agent Mode + Central Hub:** Prometheus Agent в каждом кластере, Remote Write в VictoriaMetrics/Mimir (расположенных в Management-кластере или отдельной инфраструктуре). Стандарт для мультикластерной среды. Детали — [Remote Read / Remote Write](../../Prometheus/scaling/remote_read_write.md).

**V3: Cluster + Project Monitoring:** сочетание обоих уровней: кластерный Prometheus (инфраструктура) + Федератор (приложения по проектам) для изоляции прав и нагрузки.

**Связанные темы:**

* [Обзор kube-prometheus-stack](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md) — детализация Helm-параметров upstream-чарта.
* [Prometheus Operator: концепции](../../Prometheus/kubernetes/operator/concepts.md) — паттерн оператора и все CRD.
* [Remote Read / Remote Write](../../Prometheus/scaling/remote_read_write.md) — агрегация метрик между кластерами.
* [VictoriaMetrics](../../VictoriaMetrics/overview.md) — высокопроизводительное долгосрочное хранилище.
* [rancher_overview](./rancher_overview.md) — архитектура платформы Rancher.
* [Rancher RKE: кластеры](./rancher_rke.md) — мониторинг RKE2/K3s и компонентов.
* [OpenTelemetry: архитектура](../../OpenTelemetry/architecture_signals.md) — основы работы с сигналами OTel.
