# Онлайн-установка (kube-prometheus-stack)

> [Назад к оглавлению](../overview.md)

> **SSoT для темы:** стандартная установка kube-prometheus-stack в Kubernetes с доступом к интернету через Helm.  
> **Смежные темы:** [Обзор kube-prometheus-stack](../overview.md) — компоненты, версии, архитектура; [Offline Air-gapped Installation](./offline_airgapped_installation.md) — установка в закрытых контурах; [Persistent Volumes](./persistent_volumes.md) — настройка хранилища.

## Определения

**Онлайн-установка** — развёртывание стека мониторинга в Kubernetes-кластер с неограниченным доступом к внешним ресурсам. Helm автоматически загружает чарт из публичного репозитория (`prometheus-community`), а Kubelet загружает образы из публичных реестров (docker.io, quay.io, ghcr.io).

**Helm release** — именованный экземпляр развёрнутого чарта. Имя релиза является префиксом для большинства ресурсов (Service, Pod, Secret), что критично для автоматизации и сетевой связности.

**values.yaml** — файл переопределений параметров Helm-чарта. Позволяет кастомизировать компоненты стека без модификации шаблонов чарта и сохранять конфигурацию в системе управления версиями.

**Chart version vs App version** — Chart version — версия упаковки чарта (зависимости, шаблоны, default values). App version — версия приложения внутри чарта (например, версия Prometheus Server). При обновлении следует проверять оба значения, так как они могут расходиться.

**Sidecar containers** — вспомогательные контейнеры внутри пода. В kube-prometheus-stack типичные примеры: `config-reloader` (горячая перезагрузка конфигурации Prometheus и Alertmanager) и `kube-rbac-proxy` (безопасный проксирование запросов к Kubernetes API).

**Admission webhook** — механизм Kubernetes, который чарт использует для валидации и мутации ресурсов Prometheus Operator. При установке создаются сервис и сертификат для webhook.

**CRD lifecycle** — порядок установки, обновления и удаления Custom Resource Definitions. В онлайн-режиме Helm может управлять CRD автоматически, но при мажорных обновлениях требуется ручная проверка.

## Основные концепции

### Состав развёртываемого стека

```
helm install [RELEASE_NAME] prometheus-community/kube-prometheus-stack
    │
    ├── Prometheus Operator (Deployment)
    │       └── Управление жизненным циклом Prometheus и Alertmanager через CRD
    │
    ├── Prometheus Server (StatefulSet)
    │       └── Сбор, хранение (TSDB) и обработка метрик
    │
    ├── Alertmanager (StatefulSet)
    │       └── Обработка, группировка и маршрутизация оповещений
    │
    ├── Grafana (Deployment)
    │       └── Визуализация и преднастроенные дашборды
    │
    ├── Node Exporter (DaemonSet)
    │       └── Метрики ОС с каждого узла кластера
    │
    ├── kube-state-metrics (Deployment)
    │       └── Генерация метрик на основе объектов Kubernetes API
    │
    └── CRDs (Custom Resource Definitions)
            └── Описания ресурсов: ServiceMonitor, PodMonitor, PrometheusRule и др.
```

### Влияние имени релиза на именование ресурсов

Выбор короткого и понятного имени релиза (например, `monitoring` или `kps`) упрощает дальнейшую эксплуатацию.

| Имя релиза | Prometheus Service | Grafana Service | Secret с паролем Grafana |
|---|---|---|---|
| `monitoring` | `prometheus-operated` | `monitoring-grafana` | `monitoring-grafana` |
| `kps` | `kube-prometheus-kube-prome-prometheus` | `kube-prometheus-grafana` | `kube-prometheus-grafana` |

> **Рекомендация:** Используйте имя `monitoring` для обеспечения предсказуемости имен сервисов.

### Режимы установки CRD

В онлайн-режиме доступны три стратегии управления CRD:

| Режим | Параметр | Поведение | Рекомендация |
|---|---|---|---|
| **Автоматический** | `crds.enabled: true` (по умолчанию) | Helm создаёт CRD при `helm install` и обновляет при `helm upgrade` | Подходит для большинства случаев |
| **Пропуск** | `--skip-crds` | CRD не изменяются; управляются вручную | Используется при интеграции с GitOps (Argo CD / Flux) |
| **Ручной** | `kubectl apply -f crds/` | Полный контроль через manifests | Крупные кластеры с политиками безопасности |

> **Важно:** При переходе на новую мажорную версию чарта CRD могут изменить схему. Рекомендуется просматривать release notes и применять CRD вручную до обновления оператора.

### Sidecar containers и их роль

В подах Prometheus и Alertmanager присутствуют вспомогательные контейнеры:

| Контейнер | Компонент | Назначение |
|---|---|---|
| `config-reloader` | Prometheus / Alertmanager | Обнаруживает изменения конфигурации (через ConfigMap или Secret) и отправляет SIGHUP для горячей перезагрузки без пересоздания пода. |
| `kube-rbac-proxy` | Prometheus / Alertmanager | Ограничивает доступ к kube-apiserver, проверяя RBAC-права запрашивающего. |

Эти контейнеры управляются автоматически чартом. При использовании кастомных образов убедитесь, что они содержат необходимые утилиты (`busybox` для config-reloader).

### Admission webhooks

kube-prometheus-stack устанавливает admission webhook для валидации ресурсов Prometheus, Alertmanager и ThanosRuler перед их сохранением в etcd. Webhook использует самоподписанный сертификат, генерируемый чартом. При использовании strict Pod Security Standards может потребоваться разрешение на запуск привилегированных контейнеров.

### Флаги безопасной установки и обновления

| Флаг | Применимость | Эффект |
|---|---|---|
| `--atomic` | `install` / `upgrade` | Автоматический откат при ошибке; временный релиз очищается. |
| `--timeout` | `install` / `upgrade` | Лимит времени на развёртывание (например, `5m`). |
| `--wait` | `install` / `upgrade` | Ожидание готовности всех ресурсов перед возвратом управления. |
| `--wait-for-jobs` | `install` / `upgrade` | Ожидание завершения Jobs (например, миграций). |
| `--create-namespace` | `install` | Создание namespace при отсутствии. |

### Сравнение с offline-установкой

| Параметр | Online | Offline (Air-gapped) |
|---|---|---|
| Источник чарта | GitHub Pages (автоматически) | Локальный Registry (OCI) или файл |
| Источник образов | Публичные Registry | Приватный Harbor/Nexus/Artifactory |
| Конфигурация образов | Значения по умолчанию | Обязательное переопределение `global.imageRegistry` |
| Трудозатраты | Низкие (одна команда) | Высокие (зеркалирование образов, подготовка чарта) |

## Практические сценарии

### Сценарий 1: Быстрый старт (Minimal install)

Подходит для тестирования, разработки (Sandbox) или локальных кластеров (Minikube/Kind).

```bash
# Добавление репозитория
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Установка в пространство имен monitoring
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace
```

### Сценарий 2: Промышленная установка (Production-ready)

Использование `values.yaml` для настройки отказоустойчивости, персистентности и лимитов ресурсов.

**1. Подготовка values.yaml:**

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    replicas: 2
    retention: 30d
    resources:
      requests:
        cpu: 500m
        memory: 2Gi
      limits:
        cpu: 2000m
        memory: 8Gi
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: longhorn # Или локальная StorageClass (openebs, local-path)
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 100Gi

grafana:
  adminPassword: "strong-password-here"
  persistence:
    enabled: true
    size: 10Gi
  ingress:
    enabled: true
    ingressClassName: nginx
    hosts:
      - grafana.company.tld

alertmanager:
  alertmanagerSpec:
    replicas: 3
    storage:
      volumeClaimTemplate:
        spec:
          storageClassName: longhorn
          resources:
            requests:
              storage: 5Gi
```

**2. Установка:**

```bash
helm install monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace \
  -f values.yaml
```

### Сценарий 3: Безопасное обновление через helm-diff

Плагин `helm-diff` позволяет увидеть планируемые изменения в манифестах до их применения, что предотвращает случайное удаление ресурсов.

```bash
# Установка плагина (выполняется один раз)
helm plugin install https://github.com/databus23/helm-diff

# Просмотр изменений перед обновлением
helm diff upgrade monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f values.yaml

# Применение обновлений
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f values.yaml
```

### Сценарий 4: Тестирование и верификация (helm test)

После установки или обновления рекомендуется запустить встроенные тесты Helm для проверки доступности компонентов.

```bash
# Запуск тестов
helm test monitoring -n monitoring

# Проверка статуса подов и сервисов
kubectl get all -n monitoring -l release=monitoring

# Проверка созданных CRD
kubectl get crd | grep monitoring.coreos.com
```

### Сценарий 5: Получение доступа к UI (Port-forward)

Если Ingress не настроен, можно использовать временный проброс портов.

```bash
# Grafana (доступ по http://localhost:3000)
kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80

# Prometheus UI (доступ по http://localhost:9090)
kubectl -n monitoring port-forward svc/prometheus-operated 9090:9090
```

### Сценарий 6: Учётные данные и секреты

**Получение пароля администратора Grafana (если не задан в values.yaml):**

```bash
kubectl -n monitoring get secret monitoring-grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d; echo
```

### Сценарий 7: Полная валидация перед установкой

Перед применением чарта в production выполните синтаксическую и семантическую проверку.

```bash
# 1. Lint values.yaml (проверка типов и обязательных полей)
helm lint prometheus-community/kube-prometheus-stack -f values.yaml

# 2. Рендеринг манифестов без применения
helm template monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f values.yaml > rendered.yaml

# 3. Проверка через kubectl dry-run
kubectl apply --dry-run=client -f rendered.yaml

# 4. Проверка на наличие чувствительных данных в логах (не должно быть secrets в plain text)
grep -i "password\|token\|secret" rendered.yaml | grep -v "kind: Secret" || echo "OK: plain-text secrets not found"
```

### Сценарий 8: Атомарное обновление с автоматическим откатом

Использование `--atomic` гарантирует, что при любой ошибке развёртывания Helm автоматически откатит релиз к предыдущей версии.

```bash
# Обновление с атомарностью и таймаутом
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f values.yaml \
  --atomic \
  --timeout 5m \
  --wait

# Если обновление завершится ошибкой, Helm автоматически выполнит:
# helm rollback monitoring <previous_revision> -n monitoring
```

### Сценарий 9: Управление жизненным циклом CRD

Для GitOps-сред или крупных кластеров рекомендуется устанавливать CRD отдельно от приложения.

```bash
# Экспорт CRD из чарта
helm pull prometheus-community/kube-prometheus-stack --version 88.1.x --untar
cd kube-prometheus-stack/crds

# Применение CRD (требует cluster-admin)
kubectl apply -f .

# Установка чарта с пропуском CRD
helm install monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring \
  --skip-crds \
  -f values.yaml
```

### Сценарий 10: Настройка imagePullSecrets для публичных и приватных реестров

Даже в онлайн-режиме могут требоваться секреты для rate-limited registry (docker.io) или корпоративных зеркал.

```yaml
# values.yaml
imagePullSecrets:
  - name: dockerhub-pull-secret

# Или глобально для всех компонентов:
global:
  imagePullSecrets:
    - name: dockerhub-pull-secret

# Создание секрета (если registry требует аутентификации):
kubectl create secret docker-registry dockerhub-pull-secret \
  -n monitoring \
  --docker-server=https://index.docker.io/v1/ \
  --docker-username=<user> \
  --docker-password=<password>
```

### Сценарий 11: Конфигурация безопасности (Pod Security Standards)

Kubernetes 1.25+ использует Pod Security Standards (PSS) вместо Pod Security Policies (PSP). kube-prometheus-stack требует привилегированного доступа для некоторых sidecar-контейнеров.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    podSecurityContext:
      runAsNonRoot: true
      runAsUser: 1000
      fsGroup: 1000
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities:
        drop:
          - ALL

# Namespace-лейбл для enforcement level (restricted)
kubectl label namespace monitoring \
  pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/enforce-version=v1.28
```

> **Примечание:** Если namespace помечен как `restricted`, может потребоваться добавление исключений для sidecar-контейнеров, которым необходим доступ к файловой системе хоста (например, config-reloader).

## Валидация после внедрения

### Предварительная проверка (Pre-flight)

```bash
# Проверка доступности Helm-репозитория
helm repo list
# → prometheus-community    https://prometheus-community.github.io/helm-charts

# Проверка доступной версии чарта
helm search repo prometheus-community/kube-prometheus-stack --versions | head -5

# Проверка синтаксиса values.yaml
helm template monitoring prometheus-community/kube-prometheus-stack -f values.yaml --debug | head -20
```

### Пост-инсталляционная проверка

```bash
# 1. Статус релиза
helm list -n monitoring
# → monitoring  kube-prometheus-stack  ...  deployed

# 2. Статус подов
kubectl get pods -n monitoring
# Все поды должны быть в состоянии Running (IMAGE_PULL_BACKOFF / Pending — ошибка)

# 3. События namespace
kubectl get events -n monitoring --sort-by='.lastTimestamp'

# 4. Доступность UI
kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80 &
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/api/health
# → 200

# 5. Метрики Node Exporter
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job=="node-exporter") | .health'
# → up

# 6. CRD установлены
kubectl get crd | grep -E 'servicemonitors|prometheusrules|alertmanagerconfigs'
```

## Диагностика и устранение проблем

| Проблема | Причина | Решение |
|---|---|---|
| `ImagePullBackOff` | Rate limit на docker.io или отсутствие доступа | Настройте `global.imagePullSecrets` или корпоративное зеркало; проверьте NAT/Firewall. |
| `Pending` поды | Недостаточно ресурсов (CPU/RAM) или проблемы с PVC | Выполните `kubectl describe pod`; проверьте квоты и StorageClass. |
| `Error: failed pre-install` | Ошибка в values.yaml или отсутствие namespace | Выполните `helm lint`; проверьте `--create-namespace` или создайте namespace вручную. |
| `Error: UPGRADE FAILED` | Несовместимость значений или CRD | Выполните `helm history`; откатитесь через `helm rollback`; проверьте CRD schema. |
| CRD не создаются | Конфликт с существующими CRD | Удалите старые CRD вручную; используйте `--skip-crds` только при ручном управлении. |
| Targets в статусе DOWN | Неверные селекторы в ServiceMonitor | Проверьте labels на сервисе и `matchLabels` в ServiceMonitor. |
| Grafana 404/502 (Ingress) | Ошибка в конфигурации путей | Проверьте `grafana.ingress.path` и `pathType` (обычно Prefix). |
| Webhook certificate error | Сертификат webhook недействителен | Проверьте секрет `monitoring-kube-prometheus-stack-admission`; переустановите чарт. |
| ConfigMap не обновляется | config-reloader не может записать в Secret | Проверьте права ServiceAccount и наличие sidecar-контейнера. |

## Пограничные случаи

1. **Namespace уже существует:** Helm с `--create-namespace` не перезаписывает существующий namespace, но может конфликтовать с существующими ресурсами. Убедитесь, что namespace чист.
2. **CRD конфликтуют с существующими ресурсами:** При обновлении чарта на новую мажорную версию CRD могут изменить `storage` версию. Существующие объекты Prometheus/Alertmanager могут стать невалидными. Применяйте CRD отдельно и проверяйте `kubectl get servicemonitor --validate=true`.
3. **Webhook timeout:** При высокой латентности сети admission webhook может не успеть ответить за 5 секунд. Увеличьте `failurePolicy` на `Ignore` для продакшна или настройте `timeoutSeconds` в ValidatingWebhookConfiguration.
4. **PVC pending из-за StorageClass:** В онлайн-установке StorageClass может отсутствовать в кластере. Создайте её заранее или используйте `volumeBindingMode: WaitForFirstConsumer`.
5. **Длинные имена релизов:** Kubernetes обрезает имена ресурсов до 63 символов. При имени релиза длиннее 20 символов имена сервисов могут стать непредсказуемыми.
6. **Конфликт портов:** Prometheus (9090), Alertmanager (9093) и Grafana (3000) должны быть свободны в namespace. Если порты заняты, переопределите `service.port` в values.yaml.
7. **Prometheus 3.0 breaking changes:** При обновлении на Prometheus 3.0 проверьте release notes: изменены пути API, удалены старые форматы конфигурации. Обязательно тестируйте в staging.
8. **RBAC ограничения:** ServiceAccount оператора должен иметь права на чтение/запись core/v1, apps/v1, networking.k8s.io. Вtightened-средах привилегии могут быть ограничены.
9. **Часовой пояс и время хранения:** Prometheus хранит метки времени в UTC. Убедитесь, что NTP синхронизирован на всех нодах, иначе retention может сработать некорректно.
10. **Сетевая изоляция:** Если включены NetworkPolicies, убедитесь, что порты 9090, 9093, 3000 и 9100 открыты между подами в namespace monitoring.

## Рекомендации по эксплуатации (Best Practices)

1.  **Выделенный Namespace:** Всегда используйте отдельный namespace (например, `monitoring`) для изоляции ресурсов.
2.  **Фиксация версий:** При установке в production всегда указывайте версию чарта: `--version 88.1.x`.
3.  **Персистентность для TSDB:** Никогда не используйте `emptyDir` для Prometheus в production. Данные будут потеряны при любом перезапуске пода.
4.  **Лимиты ресурсов:** Настраивайте `resources.requests` максимально близко к `resources.limits` для Prometheus, чтобы избежать OOMKill при всплесках нагрузки.
5.  **Безопасность (NetworkPolicies):** Включайте сетевые политики в `values.yaml` для ограничения доступа к компонентам мониторинга:
    ```yaml
    prometheus:
      networkPolicy:
        enabled: true
    ```
6.  **Атомарные обновления:** Используйте `--atomic` и `--timeout` для предотвращения частично развёрнутых релизов.
7.  **Бэкап перед обновлением:** Экспортируйте значения релиза и пользовательские ресурсы перед каждым `helm upgrade`:
    ```bash
    helm get values monitoring -n monitoring > backup-values.yaml
    kubectl get servicemonitor,podmonitor,prometheusrule,alertmanagerconfig \
      -n monitoring -o yaml > backup-custom-resources.yaml
    ```
8.  **Валидация:** Всегда запускайте `helm lint` и `helm template` перед установкой в production.
9.  **Секреты для registry:** Если используете корпоративное зеркало или rate-limited docker.io, настройте `global.imagePullSecrets`.
10. **Pod Security Standards:** Настройте `podSecurityContext` и `securityContext` в соответствии с enforcement level namespace. Тестируйте обновления в кластере с `restricted` режимом заранее.

## Откат и очистка

### Откат обновления

```bash
# Просмотр истории релиза
helm history monitoring -n monitoring

# Откат на предыдущую ревизию
helm rollback monitoring 1 -n monitoring

# Откат с атомарностью (если rollback может занять время)
helm rollback monitoring 1 -n monitoring --timeout 5m --wait
```

### Полное удаление стека

```bash
# Удаление релиза (сохраняет PersistentVolumeClaims по умолчанию)
helm uninstall monitoring -n monitoring

# При необходимости удалите PVC вручную
kubectl delete pvc -n monitoring -l app.kubernetes.io/instance=monitoring

# Удаление namespace (опционально)
kubectl delete namespace monitoring
```

### Очистка CRD

> **Предупреждение:** Удаление CRD приведёт к потере всех объектов Prometheus, ServiceMonitor, PodMonitor и PrometheusRule в кластере.

```bash
# Просмотр CRD перед удалением
kubectl get crd | grep monitoring.coreos.com

# Удаление только если вы уверены
kubectl delete crd prometheuses.monitoring.coreos.com
kubectl delete crd alertmanagers.monitoring.coreos.com
kubectl delete crd servicemonitors.monitoring.coreos.com
kubectl delete crd podmonitors.monitoring.coreos.com
kubectl delete crd prometheusrules.monitoring.coreos.com
```

## Полезные команды для отладки

```bash
# Просмотр логов оператора (основной источник правды при ошибках конфигурации)
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator

# Проверка событий в пространстве имен
kubectl get events -n monitoring --sort-by='.lastTimestamp'

# Описание конкретного ресурса (например, Prometheus)
kubectl describe prometheus monitoring-kube-prometheus-prometheus -n monitoring

# Проверка итоговой конфигурации всех образов в рендере
helm template monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring -f values.yaml | grep "image:" | sort -u

# Проверка статуса подов и причин ошибок загрузки
kubectl describe pod -n monitoring <pod-name> | grep -A 5 Events

# Проверка доступности реестра с узла (containerd/docker)
crictl pull docker.io/prom/prometheus:latest

# Проверка истории релиза
helm history monitoring -n monitoring
```

## Связанные ресурсы

* [Обзор kube-prometheus-stack](../overview.md) — детальное описание компонентов.
* [Persistent Volumes для мониторинга](./persistent_volumes.md) — подробные сценарии работы с хранилищем.
* [Установка в закрытом контуре (Offline Air-gapped)](./offline_airgapped_installation.md) — инструкции для изолированных сред.