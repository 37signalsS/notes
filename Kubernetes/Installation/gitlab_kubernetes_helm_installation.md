# Установка GitLab в Kubernetes через Helm

Руководство по развертывании GitLab в кластере Kubernetes при помощи официального Helm-чарта.

> **Контекст:** Официальный чарт GitLab — полноценное решение для production-развертывания. Включает Ingress, cert-manager, Prometheus, Redis и другие зависимости. См. [Обзор Helm](../ToolsUtilities/Helm/helm_overview.md), [Структура Helm-чарта](../ToolsUtilities/Helm/helm_chart_structure.md).

---

## Определения

| Термин | Описание |
|--------|----------|
| **GitLab Helm Chart** | Официальный Helm-чарт для развертывания GitLab в Kubernetes. Включает все компоненты: GitLab Rails, Sidekiq, Gitaly, PostgreSQL, Redis, Ingress, cert-manager |
| **Таймаут установки** | Максимальное время ожидания завершения установки. Для GitLab рекомендуется 600s (10 минут) из-за большого количества компонентов |
| **StorageClass** | Kubernetes-объект для динамического выделения PersistentVolume. Требуется для хранения данных GitLab (NFS, Ceph, облачные решения) |
| **MetalLB** | Решение для реализации сервиса типа LoadBalancer в bare-metal кластерах. По умолчанию в kubeadm/k3s LoadBalancer не работает |

**Навигация:** [GitLab CI Basics](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md) | [Интеграция GitLab с Harbor](./k3s_dev_environment/gitlab_harbor_integration.md)

---

## Основные концепции

### Архитектура официального чарта

Официальный чарт GitLab (`gitlab/gitlab`) — это полноценное решение для production, включающее:

- **GitLab Rails** — основное веб-приложение
- **Sidekiq** — фоновая обработка задач
- **Gitaly** — сервис для работы с Git-репозиториями
- **PostgreSQL** — база данных
- **Redis** — кэш и очередь задач
- **Ingress** — маршрутизация внешнего трафика
- **cert-manager** — управление SSL/TLS сертификатами
- **Prometheus** — мониторинг (опционально)

### Предварительные требования

| Компонент | Требование | Примечание |
|-----------|------------|------------|
| **Kubernetes** | >= 1.24 | Рекомендуется 1.26+ |
| **Helm** | >= 3.9.4 | См. [Установка CLI в Helm Overview](../ToolsUtilities/Helm/helm_overview.md#установка-cli) |
| **StorageClass** | Обязателен | NFS, Ceph, облачные PV |
| **Ingress Controller** | Включён в чарт | Можно использовать внешний |
| **cert-manager** | Включён в чарт | Можно отключить при наличии внешнего |
| **CPU** | >= 4 ядер | Минимум для тестовых сценариев |
| **RAM** | >= 8 ГБ | Минимум, рекомендуется 16+ ГБ |

### Ключевые параметры values.yaml

| Параметр | Описание | Пример значения |
|----------|----------|-----------------|
| `global.hosts.domain` | Основной домен GitLab | `example.com` |
| `global.hosts.gitlab.name` | Полное имя хоста GitLab | `gitlab.example.com` |
| `global.hosts.gitlab.ip` | Внешний IP для доступа | `192.168.1.50` |
| `certmanager.install` | Установка cert-manager | `true` / `false` |
| `nginx-ingress.enabled` | Встроенный ingress-контроллер | `true` / `false` |
| `global.registry.enabled` | Встроенный Docker Registry | `true` / `false` |
| `gitlab-runner.install` | Установка GitLab Runner | `true` / `false` |

---

## Практические сценарии

### 1. Установка Helm CLI

Если Helm ещё не установлен, используйте официальный скрипт:

```bash
curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3
chmod 700 get_helm.sh
./get_helm.sh
helm version
```

> **Актуальная версия:** Проверяйте [github.com/helm/helm/releases](https://github.com/helm/helm/releases).

### 2. Добавление репозитория GitLab

```bash
# Добавление репозитория
helm repo add gitlab https://charts.gitlab.com/
# → "gitlab" has been added to your repositories

# Обновление локальных кэшей
helm repo update
# → Hang tight while we grab the latest from your chart repositories...
```

### 3. Скачивание чарта для изучения

Перед установкой рекомендуется изучить структуру чарта и доступные параметры:

```bash
# Скачивание и распаковка чарта
helm pull gitlab/gitlab --untar

# Переход в директорию чарта
cd gitlab

# Просмотр структуры
ls -la
# → charts/  Chart.yaml  values.yaml  templates/  README.md  ...

# Изучение values.yaml
cat values.yaml
```

**Флаг `--untar`** — сразу распаковывает чарт в директорию `gitlab/`. Без флага скачивается архив `gitlab-*.tgz`.

**Опционально — указание директории:**

```bash
helm pull gitlab/gitlab --untar --untardir ./gitlab-chart
```

### 4. Базовая установка

```bash
# Создание namespace
kubectl create namespace gitlab
# → namespace/gitlab created

# Установка GitLab с минимальными параметрами
helm upgrade --install gitlab gitlab/gitlab \
  --namespace gitlab \
  --timeout 600s \
  --set global.hosts.domain=example.com \
  --set global.hosts.gitlab.name=gitlab.example.com
```

**Параметры команды:**

| Флаг | Описание |
|------|----------|
| `--install` | Устанавливает чарт, если он ещё не развёрнут |
| `--timeout 600s` | 10 минут на полную установку (по умолчанию 300s) |
| `--namespace gitlab` | Namespace для развертывания |
| `--set key=value` | Переопределение значений из values.yaml |

### 5. Установка с external URL и отключением cert-manager

Если cert-manager уже установлен в кластере или используется внешний:

```bash
helm upgrade --install gitlab gitlab/gitlab \
  --namespace gitlab \
  --timeout 600s \
  --set global.hosts.domain=example.com \
  --set global.hosts.gitlab.name=gitlab.example.com \
  --set certmanager.install=false \
  --set certmanager-issuer.email=admin@example.com
```

### 6. Проверка состояния после установки

```bash
# Просмотр всех ресурсов в namespace
kubectl get all -n gitlab

# Проверка pod'ов
kubectl get pods -n gitlab
# → NAME                          READY   STATUS    RESTARTS   AGE
#   gitlab-gitlab-rails-xxx       1/1     Running   0          5m
#   gitlab-gitaly-xxx             1/1     Running   0          5m
#   gitlab-postgresql-xxx         1/1     Running   0          5m

# Проверка сервисов
kubectl get svc -n gitlab

# Проверка PersistentVolumeClaims
kubectl get pvc -n gitlab
```

### 7. Решение проблем с хранилищем

#### Проблема: PVC не могут перейти в статус Bound

**Симптом:** Pod'ы в статусе `Pending`, PVC в статусе `Pending` с событием `no persistent volumes available for this claim and no storage class is set`.

**Причины:**

- StorageClass не установлен как default
- Недостаточно места на NFS-сервере для удовлетворения запросов PVC
- Старые PVC не удалены при повторной установке чарта

**Решение — сделать StorageClass дефолтным:**

```bash
# Установка аннотации для NFS StorageClass
kubectl patch storageclass nfs \
  -p '{"metadata": {"annotations": {"storageclass.kubernetes.io/is-default-class": "true"}}}'
# → storageclass.storage.k8s.io/nfs patched

# Проверка — (default) должен появиться в выводе
kubectl get storageclass
# → NAME            PROVISIONER     RECLAIMPOLICY   VOLUMEBINDINGMODE   ALLOWVOLUMEEXPANSION   AGE
#   nfs (default)   k8s-sigs.io/nfs-subdir-external-provisioner   Delete          Immediate           false                  10m
#   standard        k8s-sigs.io/nfs-subdir-external-provisioner   Delete          Immediate           false                  15m
```

**Решение — очистка старых PVC перед переустановкой:**

```bash
# Удаление чарта
helm uninstall gitlab -n gitlab

# Удаление всех PVC из namespace
kubectl delete pvc --all -n gitlab
# → persistentvolumeclaim "..." deleted

# Проверка — PVC должны отсутствовать
kubectl get pvc -n gitlab
# → No resources found in gitlab namespace.
```

> **Важно:** PVC не удаляются автоматически при `helm uninstall`. При повторной установке старые PVC могут конфликтовать с новыми. Всегда очищайте PVC перед переустановкой.

#### Проблема: PVC запрашивают слишком много места

**Симптом:** На NFS-сервере выделено 10 ГиБ, но все sub-charts GitLab запрашивают по 8 ГиБ каждый. Суммарный запрос превышает доступное место.

**По умолчанию** официальный чарт GitLab настраивает следующие запросы на хранилище:

| Sub-chart | PVC по умолчанию | Минимально для тестов |
|-----------|-----------------|----------------------|
| **PostgreSQL** | 8Gi | 1Gi |
| **MinIO** (object storage) | 10Gi | 1Gi |
| **Redis** | 8Gi | 1Gi |
| **Gitaly** (Git-репозитории) | 50Gi | 1Gi |
| **Prometheus** | 8Gi | можно отключить |
| **AlertManager** | 2Gi | можно отключить |

**Решение — уменьшение запросов PVC через values.yaml:**

Для сценариев с ограниченным хранилищем (лабораторные среды, NFS на одной ноде) настройте каждый sub-chart:

```yaml
# gitlab-values.yaml — минимальное хранилище для тестов

# PostgreSQL
postgresql:
  primary:
    persistence:
      size: 1Gi

# MinIO (object storage)
minio:
  persistence:
    size: 1Gi

# Redis
redis:
  master:
    persistence:
      size: 1Gi

# Gitaly — хранение Git-репозиториев
global:
  gitaly:
    enabled: true
    persistence:
      size: 1Gi

# Отключение Prometheus для экономии места
prometheus:
  install: false
```

> **Примечание:** Не все sub-charts позволяют изменить размер через основной `values.yaml`. В некоторых случаях требуется редактирование `charts/<subchart>/values.yaml` внутри распакованного чарта.

#### Решение проблем с ресурсами (CPU/RAM)

**Симптом:** Pod'ы в статусе `Pending`

**Причины:**

- Недостаточно CPU/RAM на нодах
- (см. проблемы с хранилищем выше)

**Решение — проверка ресурсов:**

```bash
# Использование ресурсов нодами
kubectl top nodes

# Использование ресурсов подами
kubectl top pods -n gitlab
```

**Настройка StorageClass для bare-metal:**

Для bare-metal кластеров рекомендуется NFS:

```yaml
# nfs-storageclass.yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: nfs-storage
provisioner: k8s-sigs.io/nfs-subdir-external-provisioner
parameters:
  archiveOnDelete: "false"
```

```bash
kubectl apply -f nfs-storageclass.yaml

# Если не хотите делать дефолтным — укажите StorageClass явно в values:
# global.persistence.storageClass: nfs-storage
```

### 8. Работа с LoadBalancer в bare-metal

По умолчанию сервис типа LoadBalancer не работает в kubeadm/k3s кластерах.

**Варианты решения:**

| Решение | Описание | Когда использовать |
|---------|----------|-------------------|
| **MetalLB** | Программный LoadBalancer для bare-metal | Production bare-metal |
| **Ingress + NodePort** | Маршрутизация через Ingress на NodePort | Тестовые сценарии |
| **ExternalIPs** | Прямое указание IP ноды | Простые сценарии |

**Указание внешнего IP ноды:**

```bash
# Узнаём внешний IP ноды
kubectl get nodes -o wide
# → EXTERNAL-IP колонка

# Установка с указанием IP
helm upgrade --install gitlab gitlab/gitlab \
  --namespace gitlab \
  --timeout 600s \
  --set global.hosts.domain=example.com \
  --set global.hosts.gitlab.ip=192.168.1.50
```

### 9. Доступ к GitLab через NodePort

Если в кластере отсутствует Ingress Controller или MetalLB, можно использовать сервис типа NodePort для доступа к веб-интерфейсу.

**Проверка текущего сервиса:**

```bash
# Просмотр сервисов в namespace
kubectl get svc -n gitlab
# → NAME              TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)          AGE
#   gitlab-webservice ClusterIP   10.96.100.50    <none>        8181/TCP         10m
```

**Изменение типа сервиса на NodePort:**

```bash
# Обновление чарта с включением NodePort для web-сервиса
helm upgrade --install gitlab gitlab/gitlab \
  --namespace gitlab \
  --timeout 600s \
  --set global.hosts.domain=example.com \
  --set global.hosts.gitlab.name=gitlab.example.com \
  --set nginx-ingress.enabled=false \
  --set gitlab.webservice.service.type=NodePort
```

**Получение внешнего IP ноды и порта:**

```bash
# Получение IP ноды
kubectl get nodes -o wide
# → EXTERNAL-IP колонка (например, 192.168.1.10)

# Получение назначенного NodePort
kubectl get svc -n gitlab gitlab-webservice
# → PORT(S) колонка: 8181:30336/TCP (30336 — внешний порт)
```

**Доступ к веб-интерфейсу:**

```
http://<EXTERNAL-IP-НОДЫ>:<NODEPORT>
# Пример: http://192.168.1.10:30336
```

> **Примечание:** NodePort выделяет порт из диапазона 30000–32767. Для production используйте Ingress + TLS.

### 10. Получение начального пароля root

После установки GitLab начальный пароль для пользователя `root` хранится в секрете Kubernetes.

```bash
# Получение секрета с начальным паролем
kubectl get secret -n gitlab gitlab-initial-root-password \
  -o jsonpath='{.data.password}' | base64 -d
# → <начальный-пароль-root>

# Альтернативно — полный вывод секрета
kubectl get secret -n gitlab gitlab-initial-root-password -o yaml
```

**Первый вход:**

- **Логин:** `root`
- **Пароль:** значение из секрета `gitlab-initial-root-password`

> **Важно:** При первом входе GitLab потребует сменить пароль. Если возникает ошибка 422 «The change you requested was rejected» — проверьте, что все pod'ы перешли в статус `Running` и отсутствуют ошибки в логах.

### 11. Установка GitLab Runner

GitLab Runner устанавливается как отдельный чарт:

```bash
# Добавление репозитория Runner
helm repo add gitlab https://charts.gitlab.com/
helm repo update

# Установка Runner
helm install gitlab-runner gitlab/gitlab-runner \
  --namespace gitlab \
  --set gitlabUrl=https://gitlab.example.com \
  --set runnerRegistrationToken=<TOKEN>
```

**Параметр `run.privileged=true`:**

Для полноценной работы Runner (например, DinD — Docker-in-Docker) требуется привилегированный режим:

```bash
helm install gitlab-runner gitlab/gitlab-runner \
  --namespace gitlab \
  --set gitlabUrl=https://gitlab.example.com \
  --set runnerRegistrationToken=<TOKEN> \
  --set run.privileged=true
```

> **Предупреждение:** Привилегированный режим снижает безопасность кластера. Используйте только в доверенных окружениях.

---

## Дополнительная информация

### Типичная структура values.yaml для production

```yaml
# gitlab-values.yaml
global:
  hosts:
    domain: example.com
    https: true
    gitlab:
      name: gitlab.example.com
      ip: 192.168.1.50
  
  # Отключение встроенного Registry при использовании Harbor
  registry:
    enabled: false
  
  # Настройка Ingress
  ingress:
    configureCertmanager: true
    tls:
      enabled: true

# Отключение cert-manager при наличии внешнего
certmanager:
  install: false

# Встроенный ingress-контроллер
nginx-ingress:
  enabled: true

# Отключение установки Runner (устанавливается отдельно)
gitlab-runner:
  install: false
```

```bash
# Установка с values-файлом
helm upgrade --install gitlab gitlab/gitlab \
  --namespace gitlab \
  -f gitlab-values.yaml \
  --timeout 600s
```

### Ограничения чарта

| Аспект | Ограничение | Рекомендация |
|--------|-------------|--------------|
| **Тестовый режим** | Чарт по умолчанию устанавливается с ограничениями для оценки | Для production настройте ресурсы, хранилище, TLS |
| **GitLab Runner** | Без `run.privileged=true` недоступен DinD | Включайте только в доверенных кластерах |
| **Хранилище** | Требует настроенный StorageClass; sub-charts запрашивают 8–50 Gi каждый | Используйте NFS, Ceph или облачные решения; уменьшайте size для тестов |
| **LoadBalancer** | Не работает без MetalLB в bare-metal | Установите MetalLB или используйте NodePort |
| **Gitaly** | Компонент для работы с Git-репозиториями, обязателен | При `global.gitaly.enabled: false` требуется внешний Gitaly |
| **PVC при удалении** | `helm uninstall` не удаляет PVC | Всегда удаляйте PVC вручную перед переустановкой |

### Связанные темы

- [Обзор Helm](../ToolsUtilities/Helm/helm_overview.md) — основы работы с Helm
- [Структура Helm-чарта](../ToolsUtilities/Helm/helm_chart_structure.md) — организация файлов чарта
- [Интеграция GitLab с Harbor](./k3s_dev_environment/gitlab_harbor_integration.md) — отключение Registry и настройка внешнего реестра
- [GitLab CI Basics](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md) — основы CI/CD в GitLab
- [Docker-in-Docker](../../Docker/docker-in-docker.md) — запуск Docker внутри контейнера (требует privileged-режим)
