# Установка Prometheus в Kubernetes через Helm

Этот файл служит указателем на актуальные инструкции по развертыванию стека мониторинга с использованием Helm-чарта `kube-prometheus-stack`.

## Определения

**Helm release** — именованный экземпляр развёрнутого чарта. Имя релиза является префиксом для большинства ресурсов (Service, Pod, Secret), что критично для автоматизации и сетевой связности.

**values.yaml** — файл переопределений параметров Helm-чарта. Позволяет кастомизировать компоненты стека без модификации шаблонов чарта и сохранять конфигурацию в системе управления версиями.

**Chart version vs App version** — Chart version — версия упаковки чарта (зависимости, шаблоны, default values). App version — версия приложения внутри чарта (например, версия Prometheus Server). При обновлении следует проверять оба значения.

**Air-gapped установка** — развёртывание в изолированной среде без доступа к интернету, требующее предварительной подготовки артефактов и локального реестра (Harbor/Nexus).

## Сравнение методов установки в Kubernetes

| Метод | Контроль | Сложность | Когда использовать |
|:---|:---|:---|:---|
| **Helm (kube-prometheus-stack)** | Средний | Средняя | Production, GitOps, стандартный путь |
| **Ручная установка (Operator + манифесты)** | Максимальный | Высокая | Кастомизация CRD, air-gapped без OCI |
| **APT (bare-metal/VM)** | Низкий | Низкая | Вне Kubernetes, на хостовых ОС |

> **Рекомендация:** Для Kubernetes-сред используйте Helm-чарт `kube-prometheus-stack`. Ручная установка через Operator применяется при необходимости нестандартной модизации компонентов или в air-gapped средах без поддержки OCI. Для хостовых систем (bare-metal/VM) используйте [установку через APT](./with_apt.md).

## Выбор сценария установки

| Сценарий | Ключевые требования | Ссылка |
|:---|:---|:---|
| **Онлайн (Online)** | Кластер имеет доступ к интернету, используется публичный Helm-репозиторий | [Онлайн-установка](../kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/online_installation.md) |
| **Offline/Air-gapped** | Изолированный кластер, локальный Harbor/Nexus, подготовленные артефакты | [Установка в закрытом контуре](../kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/offline_airgapped_installation.md) |

## Основные инструкции (SSoT)

Согласно архитектуре базы знаний, подробные практические сценарии разделены по типам окружения:

*   **[Онлайн-установка (Online Installation)](../kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/online_installation.md)** — основной сценарий для кластеров с доступом к интернету. Включает настройку персистентности, Ingress и лимитов ресурсов.
*   **[Установка в закрытом контуре (Offline/Air-gapped)](../kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/offline_airgapped_installation.md)** — инструкции для изолированных сред (без доступа к внешним репозиториям).

## Краткая справка

**kube-prometheus-stack** — это «umbrella chart», который объединяет:
*   **Prometheus Operator** (управление через CRD).
*   **Prometheus Server**, **Alertmanager**, **Grafana**.
*   **Node Exporter** и **Kube State Metrics**.

## Шпаргалка команд Helm

```bash
# Добавление репозитория
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Просмотр доступных версий
helm search repo prometheus-community/kube-prometheus-stack --versions

# Установка
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  -f values.yaml

# Обновление с предпросмотром изменений
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring -f values.yaml

# Откат
helm rollback monitoring -n monitoring

# Удаление
helm uninstall monitoring -n monitoring

# Просмотр истории
helm history monitoring -n monitoring
```

## Безопасность (кратко)

*   **RBAC:** Используйте выделенный ServiceAccount с минимальными правами. Operator требует `cluster-admin`; Prometheus Server — `get/list/watch` на `services`, `endpoints`, `pods`, `nodes`.
*   **NetworkPolicy:** Включайте изоляцию трафика мониторинга через `prometheus.networkPolicy.enabled: true`.
*   **Secrets:** Не храните пароли в `values.yaml`. Используйте `existingSecret` или External Secrets Operator.
*   **Pod Security:** Настройте `podSecurityContext` и `securityContext` в соответствии с enforcement level namespace.

Подробнее: [Обзор kube-prometheus-stack](../kubernetes/Kube_Prometheus_Stack_Helm/overview.md).

## Резервное копирование (кратко)

Перед каждым `helm upgrade` экспортируйте значения и пользовательские ресурсы:

```bash
helm get values monitoring -n monitoring > backup-values.yaml
kubectl get servicemonitor,podmonitor,prometheusrule,alertmanagerconfig \
  -n monitoring -o yaml > backup-custom-resources.yaml
```

Подробнее: [Обзор kube-prometheus-stack](../kubernetes/Kube_Prometheus_Stack_Helm/overview.md).

## Диагностика (кратко)

| Проблема | Быстрая диагностика |
|:---|:---|
| `ImagePullBackOff` | `kubectl describe pod <pod>` → проверка `image:` и `imagePullSecrets` |
| `Pending` поды | `kubectl get pvc -n monitoring`; проверка StorageClass |
| `Target DOWN` | `kubectl get servicemonitor -n monitoring`; проверка labels |
| `ConfigMap не обновляется` | `kubectl logs -n monitoring -l app=prometheus -c configmap-reload` |
| `OOMKilled` | `kubectl describe pod <pod>` → проверка `limits.memory` |

Подробнее: [Обзор kube-prometheus-stack](../kubernetes/Kube_Prometheus_Stack_Helm/overview.md).

## См. также

*   **[Обзор kube-prometheus-stack](../kubernetes/Kube_Prometheus_Stack_Helm/overview.md)** — описание компонентов и версий.
*   **[Helm: общие сведения](../../Kubernetes/ToolsUtilities/Helm/helm_overview.md)**.
*   **[Ручная установка Prometheus Operator](../../Prometheus/kubernetes/operator/installation.md)** — установка без Helm.
*   **[Установка Prometheus через APT](./with_apt.md)** — для хостовых систем.
*   **[HA Setup](./ha_setup.md)** — практическое развертывание HA для bare-metal сред.
