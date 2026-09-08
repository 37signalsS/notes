# Установка Rancher Server

## Определения

**Rancher Server** — центральный компонент управления (Management Plane), обеспечивающий оркестрацию мультикластерных сред, управление безопасностью и автоматизацию жизненного цикла Kubernetes.

**Management Cluster (Local)** — выделенный кластер Kubernetes (рекомендуется RKE2), предназначенный исключительно для работы Rancher Server. 
*   **Правило эксплуатации:** запрещено запускать бизнес-нагрузки в Local-кластере для предотвращения деградации производительности панели управления.

**Bootstrap Password** — временный пароль администратора, задаваемый при первой установке. В современных версиях (v2.10+) рекомендуется передавать его через секреты Kubernetes или параметры Helm для соблюдения стандартов безопасности (Secret Management).

**cert-manager** — инструмент автоматизации PKI в Kubernetes. Для Rancher v2.13+ рекомендуется версия **v1.20+** с поддержкой Gateway API.

## Базовые концепции

### Выбор базовой инфраструктуры (2026)

Для Management-кластера в высоконагруженных средах (100+ управляемых кластеров) рекомендуется следующая конфигурация:

| Параметр | **RKE2** (Standard) | **K3s** (Edge/Small) |
| :--- | :--- | :--- |
| **Среда выполнения** | `containerd` | `containerd` |
| **Безопасность** | FIPS-совместимость, CIS Hardening | Профиль `hardened` (опционально) |
| **База данных** | `etcd` (обязательно SSD/NVMe) | `etcd` или `PostgreSQL` |
| **Ingress** | NGINX (Default) | Traefik / Gateway API |

### Взаимодействие Rancher Server с управляемыми кластерами

Rancher Server управляет Downstream-кластерами (управляемыми Rancher) двумя способами:

*   **Kubernetes Downstream (импортированные / провижиненные):** в каждый Downstream-кластер устанавливается `cattle-cluster-agent`, который открывает исходящее соединение к Rancher Server через **Tunnel** (на базе `rancher-tunnelserver`). Благодаря этому Rancher может управлять кластером (kubeconfig, kubectl-прокси, Rancher-операции) **без** входящего доступа к API-серверу кластера — достаточно исходящей связности с Rancher Server по TCP/443.
*   **Node Drivers / Cloud Credentials:** для провижининга кластеров на облачных или виртуальных провайдерах используется `cattle-node-agent`, который устанавливается на узлы конфигурируемого кластера и развертывает на них RKE2/K3s.

> **Практическое следствие:** для работы Rancher обязателен только **исходящий** доступ с узлов/агентов Downstream-кластеров к FQDN Rancher Server по 443 (и запись DNS). Это сильно упрощает сетевую модель по сравнению с RKE1.

### Архитектура высокой доступности (HA)

Единственный поддерживаемый метод для Production — установка в HA-кластер из **3-х Master-узлов**. Это обеспечивает отказоустойчивость `etcd` (кворум) и самого API Rancher.

*   **Перед узлами** должен находиться **Load Balancer (L7, например NGINX/Haproxy/облачный LB)**, который направляет трафик на Ingress-порты 443/80 всех трёх узлов и служит точкой входа для FQDN `rancher.example.com`.
*   **Реплики Rancher:** Deployment `rancher` масштабируется до `replicaCount: 3`; поды распределяются по узлам (анти-аффинити), при необходимости задаётся topology spread.
*   **etcd** размещается на тех же трёх узлах (RKE2) или на выделенных etcd-узлах; для стабильности критична низкая задержка дискового I/O.

```text
        ┌──────────────┐
        │ Load Balancer │  ← 443/80, FQDN rancher.example.com
        └──────┬───────┘
     ┌──────────┼──────────┐
┌────▼────┐ ┌───▼────┐ ┌───▼────┐
│ Master 1 │ │ Master 2 │ │ Master 3 │   RKE2 nodes (control-plane + etcd)
│ rancher  │ │ rancher  │ │ rancher  │   Deployment rancher, replicaCount=3
└─────────┘ └─────────┘ └─────────┘   + ingress-nginx, cert-manager
```

### Предварительные требования (проверка перед установкой)

| Область | Требование | Примечание |
| :--- | :--- | :--- |
| **Kubernetes** | Поддерживаемая версия (см. Support Matrix, например для Rancher 2.14 — v1.33–v1.35) | RKE2/K3s enable API Aggregation Layer по умолчанию |
| **API Aggregation Layer** | **Обязателен** (Rancher регистрирует extension API server) | В RKE2/K3s включён автоматически |
| **Helm client** | **3.18+** (для Rancher 2.12+) | Новые версии K8s требуют актуального Helm |
| **cert-manager** | v1.20+ (рекомендуется для Rancher v2.13+) | Для TLS-сертификатов Ingress |
| **Load Balancer** | L7 перед Ingress всех узлов | Для Production (HA) |
| **DNS** | Запись A для FQDN `rancher.example.com` → LB | Wildcard для downstream `*.example.com` — при необходимости |
| **firewalld** | **Отключить** на узлах | Несовместим с CNI-плагинами (требование Rancher) |
| **PSA** | `cattle-system` — профиль `privileged` | Rancher v2.13+ полагается на PSA |

**Ресурсы Management-кластера (официальная матрица, Rancher 2.14):**

| Размер | Макс. кластеров | Макс. узлов | vCPU на узел | RAM на узел |
| :--- | :--- | :--- | :--- | :--- |
| **Small** | 150 | 1500 | 4 | 16 GB |
| **Medium** | 300 | 3000 | 8 | 32 GB |
| **Large** | 500 | 5000 | 16 | 64 GB |
| **Larger** | масштабируется иначе | — | — | — |

> Ресурсы **узлов** Management-кластера, а не всего пула. Для типового Production достаточно конфигурации Small–Medium; размер Large+ требует специальной проработки (выгрузка в отдельное хранилище метрик, аудита и т.п.).

### Состав чарта `rancher` и развёртываемые компоненты

Helm-чарт `rancher` в namespace `cattle-system` развертывает:

*   **Deployment `rancher`** — контейнер `rancher/rancher` (API, Web UI, контроллеры management-плоскости). Реплики задаются `replicaCount`.
*   **`cattle-cluster-agent`** — не в Management-кластере, а в Downstream; используется для управления (см. выше).
*   **`cattle-webhook`** — admission webhook для валидации/мутации Rancher-ресурсов (`*.cattle.io`), Required by Rancher.
*   **`rancher-webhook`** — обвязка вебхука Rancher (устанавливается отдельным чартом в рамках процесса).
*   **Ingress** — точка входа, создаёт `Ingress` для `hostname` с TLS по выбранной стратегии.
*   **Service accounts, роль bindings, ConfigMaps** для внутренней логики Rancher.

**Как Rancher обновляет system charts:** Rancher управляет рядом внутренних `helm chart`s (`fleet`, `rancher-monitoring`, `rancher-logging`, `neuvector` и др.) через сущность **`rancher-charts`** (встроенный каталог) и **`useBundledSystemChart`**: 
*   `useBundledSystemChart=true` — Rancher использует только встроенные (bundled) версии system charts (полезно для air-gapped и стабильности версий).
*   `useBundledSystemChart=false` (по умолчанию) — Rancher при необходимости подтягивает обновлённые charts из удалённого каталога `releases.rancher.com/server-charts`.

### Каналы (channels) и версии чартов

| Канал | URL | Назначение |
| :--- | :--- | :--- |
| `rancher-latest` | `https://releases.rancher.com/server-charts/latest` | Новейшие функции; рекомендован для новых установок |
| `rancher-stable` | `https://releases.rancher.com/server-charts/stable` | Максимальная консервативность/стабильность |
| `rancher-alpha` | `https://releases.rancher.com/server-charts/alpha` | Экспериментальные сборки (pre-release) |

> Версионирование system charts в **Apps & Marketplace** использует схему major-версий начиная с `100` (например, `100.0.0+up2.1.0`) — upstream-версия указывается после `+up`. Это предотвращает конфликт инкрементов между upstream и сборками Rancher.

### Стратегии TLS/сертификатов Ingress

`ingress.tls.source` определяет источник TLS-сертификата для FQDN Rancher:

| Значение | Источник сертификата | Когда использовать |
| :--- | :--- | :--- |
| **`rancher`** (default) | Собственный CA Rancher (самоподписанный) | Быстрое развёртывание / внутренние среды |
| **`letsEncrypt`** | Let's Encrypt (через cert-manager HTTP-01) | Публичные FQDN, нужен `letsEncrypt.email` |
| **`secret`** | Вручную созданный TLS-секрет | Наличие собственного сертификата от корпоративного **Private CA** |
| **`privateCA`** (флаг `--set privateCA=true`) | Собственный CA Rancher + траст корневого CA организации | Когда сертификат выдан внутренним CA |

## Практические сценарии

### Шаг 1: Подготовка узлов и RKE2

Минимальные требования: 4 CPU, 8 GB RAM (рекомендуется 16 GB).

```bash
# /etc/rancher/rke2/config.yaml  (на каждом серверном узле)
token: "secure-bootstrap-token"
server: https://<MASTER-1-IP>:9345   # только на узлах 2 и 3; мастер-1 без этой строки
tls-san:
  - "rancher.example.com"
cni: canal # Стандарт для RKE2
```

**Разъяснение параметров:**
*   `token` — единый секрет для всех серверных/агентных узлов; используется для шифрования bootstrap-данных в datastore и для подключения новых узлов.
*   `server` — указывает на первый серверный узел (этот параметр **не** задаётся на первом узле, только на join-узлах 2 и 3).
*   `tls-san` — дополнительные имена (SAN) для сертификата Kube API: FQDN, под которым доступен сервер. Обязателен, если обращение к API идёт не по IP узла.

**Установка RKE2 (на каждом узле):**
```bash
curl -sfL https://get.rke2.io | INSTALL_RKE2_TYPE=server sh -
systemctl enable --now rke2-server
mkdir -p ~/.kube && cp /etc/rancher/rke2/rke2.yaml ~/.kube/config
```

**Проверка кластера:**
```bash
kubectl get nodes
# →  Все 3 узла в статусе Ready
kubectl get pods -n kube-system
# →  Поды ingress-nginx, core-dns, metrics-server в Running
```

> При использовании Load Balancer перед узлами убедитесь, что **tls-san включает FQDN** `rancher.example.com`, иначе проверка сертификата Kube API на узлах join завершится ошибкой.

### Шаг 2: Установка cert-manager (v1.20+)

cert-manager используется для выпуска TLS-сертификатов Ingress Rancher (стратегии `rancher`/`letsEncrypt`). Подробное руководство и параметры — в [Установка cert-manager](../ToolsUtilities/cert_manager/installation.md); здесь приведены шаги с учётом требований Rancher.

В 2026 году cert-manager требует явного включения поддержки Gateway API, если планируется его использование:

```bash
helm repo add jetstack https://charts.jetstack.io
helm repo update

helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --set installCRDs=true \
  --set config.enableGatewayAPI=true
```

**Проверка:**
```bash
kubectl -n cert-manager get pods
# →  cert-manager, cert-manager-cainjector, cert-manager-webhook  в Running
kubectl rollout status deploy/cert-manager -n cert-manager
```

> Сценарии работы с Let's Encrypt и Private CA в контексте cert-manager — в [LetsEncrypt: сценарии](../ToolsUtilities/cert_manager/LetsEncrypt/letsencrypt_scenarios.md) и [Private CA: сценарии](../ToolsUtilities/cert_manager/Private_CA/scenarios.md).

### Шаг 3: Установка Rancher Server через Helm

Для установки используйте канал `latest` (или `stable` для максимальной консервативности):

```bash
# Добавление репозитория
helm repo add rancher-latest https://releases.rancher.com/server-charts/latest

kubectl create namespace cattle-system

# Установка
helm upgrade --install rancher rancher-latest/rancher \
  --namespace cattle-system \
  --create-namespace \
  --set hostname=rancher.example.com \
  --set bootstrapPassword='Strong-C0mp1ex-Pass!' \
  --set ingress.tls.source=rancher \
  --set replicaCount=3 \
  --set global.cattle.psp.enabled=false # PSP удалены в K8s 1.25+
```

**Разъяснение ключевых параметров:**
*   `hostname` — **обязательный**, FQDN, по которому доступен Rancher (соответствует DNS и `tls-san`). От него зависит и адрес, на котором будут регистрироваться downstream-кластеры.
*   `bootstrapPassword` — временный пароль admin. **Минимальная длина — 12 символов**; если короче, Rancher может не применить его и сгенерировать случайный (см. «Диагностика»).
*   `ingress.tls.source` — см. таблицу стратегий TLS выше (`rancher` / `letsEncrypt` / `secret`).
*   `replicaCount` — число реплик Deployment `rancher`; для HA = 3.
*   `global.cattle.psp.enabled=false` — обязательно, т.к. Pod Security Policies удалены в Kubernetes 1.25+.

**Проверка готовности (Readiness):**
```bash
kubectl rollout status deployment/rancher -n cattle-system
# →  deployment "rancher" successfully rolled out
kubectl get pods -n cattle-system
# →  rancher-<hash>-<hash>          3/3     Running
# →  rancher-webhook-...           1/1     Running
```

### Первый вход и смена пароля администратора

1.  Откройте `https://rancher.example.com` в браузере (исправьте предупреждение о самоподписанном сертификате, если используется `ingress.tls.source=rancher`).
2.  Введите `bootstrapPassword` из шага установки.
3.  Система потребует **сменить пароль** на постоянный административный — обязательно сделайте это, так как bootstrap-пароль является временным.
4.  Задайте `Rancher Server URL` (должен совпадать с `hostname`) и, при необходимости, ограничения.
5.  Пройдите мастера настройки (`Add Cluster` / пропустить) и включите CBC/нейтральные настройки по необходимости.

**Если вы не задавали `bootstrapPassword`** (сгенерирован автоматически), получите его из Secret:
```bash
kubectl get secret --namespace cattle-system bootstrap-secret \
  -o go-template='{{ .data.bootstrapPassword | base64decode }}{{ "\n" }}'
```

### Использование собственного CA (Private CA)

Если организация использует внутренний удостоверяющий центр:

1.  Для выдачи сертификата собственного CA Rancher выполните установку с `--set ingress.tls.source=rancher --set privateCA=true` (собственный CA Rancher, но с подписанным/доверенным корнем организации), **либо**
    `--set ingress.tls.source=secret` и предоставьте готовый сертификат (см. ниже).
2.  При использовании `secret` — создайте TLS-секрет вручную:
    ```bash
    kubectl -n cattle-system create secret tls tls-rancher-ingress \
      --cert=./fullchain.pem --key=./privkey.pem
    ```
3.  Передайте корневой сертификат CA через `--set privateCA=true`.

**Для доверия к собственным корневым CA** (например, внутри корпоративной сети, где клиентские машины не доверяют CA Rancher) добавьте их в secret `tls-ca-additional`:
```bash
kubectl -n cattle-system create secret generic tls-ca-additional \
  --from-file=ca-additional.pem=./ca.pem
```
После этого укажите `--set additionalTrustedCAs=true`. Этот механизм также используется для доверия Downstream-кластеров к приватному CA.

> Детальные сценарии Private CA в cert-manager — в [Private CA: сценарии](../ToolsUtilities/cert_manager/Private_CA/scenarios.md) и [Operations vault/cert](../ToolsUtilities/cert_manager/Private_CA/operations.md).

### Использование Let's Encrypt

Для публичного FQDN с автоматическим выпуском сертификатов Let's Encrypt:

```bash
helm upgrade --install rancher rancher-latest/rancher \
  --namespace cattle-system \
  --set hostname=rancher.example.com \
  --set ingress.tls.source=letsEncrypt \
  --set letsEncrypt.email=admin@example.com \
  --set letsEncrypt.environment=production \
  --set bootstrapPassword='Strong-C0mp1ex-Pass!' \
  --set global.cattle.psp.enabled=false
```

**Разъяснение:**
*   `letsEncrypt.environment` — `staging` (тестовое) или `production` (по умолчанию). Для предварительной проверки используйте `staging`, чтобы не исчерпывать лимиты Let's Encrypt на ошибках.
*   Требуется публично доступные порты 80 (для HTTP-01 challenge) и 443.
*   Убедитесь, что DNS-запись FQDN указывает на Load Balancer/Ingress до установки.

### Настройка Pod Security Admission (PSA)

Rancher v2.13+ полностью полагается на PSA. Для Management-кластера по умолчанию применяется профиль `privileged`, но для внутренних неймспейсов Rancher рекомендуется:
```bash
kubectl label namespace cattle-system pod-security.kubernetes.io/enforce=privileged
```

### Тюнинг etcd (Критично)

Для стабильности Rancher Server необходимо обеспечить `etcd` минимальные задержки дискового ввода-вывода.
*   **Fsync Latency:** должна быть < 10ms.
*   **Проверка:** используйте `fio` для замера производительности перед установкой.

```bash
# Пример замеров fio (на каждом серверном узле)
fio --name=fsynctest --rw=write --bs=4k --size=256m --fdatasync=1 --runtime=30 --time_based
# →  fsync/fdatasync latency должна быть < 10ms
```

### Обновление Rancher Server (Upgrade)

**Общее правило supported upgrade path:** между **minor**-версиями (например, 2.13.x → 2.14.x) поддерживается только переход с **новейшего патча текущей minor-версии** на **новейший патч следующей minor-версии**. Сначала обязательно обновитесь до последнего патча текущей версии, затем до следующей minor.

**Подготовка:**
1.  **Сделайте резервную копию** (см. раздел «Backup/Restore») — откат после апгрейда выполняется только восстановлением из бэкапа предыдущей версии.
2.  Проверьте текущие значения чарта:
    ```bash
    helm get values rancher -n cattle-system
    ```
3.  Проверьте, что system charts (feature charts: fleet, rancher-monitoring и др.) обновлены в своей release-line — это предотвращает конфликты после апгрейда.
4.  Проверьте HELM client (для Rancher 2.12+ нужен **Helm 3.18+**).

**Апгрейд:**
```bash
helm repo update
helm upgrade rancher rancher-latest/rancher \
  --namespace cattle-system \
  --set hostname=rancher.example.com \
  --set bootstrapPassword='Strong-C0mp1ex-Pass!' \
  --set global.cattle.psp.enabled=false \
  --set replicaCount=3
```

**После апгрейда:**
```bash
kubectl rollout status deployment/rancher -n cattle-system
kubectl -n cattle-system get pods
# →  Убедиться, что rancher и rancher-webhook в Running
```

> **Известная проблема апгрейда v2.13.1→v2.13.2:** имя чарта менялось (`rancher-prime` → `rancher`), что приводит к конфликту Ingress `cattle-system/rancher-rancher-prime` и ошибке `UPGRADE FAILED: failed to create resource: admission webhook ... already defined`. Перед апгрейдом удалите старый Ingress:
> ```bash
> kubectl delete ingress rancher-rancher-prime -n cattle-system
> ```

### Резервное копирование и восстановление (Backup/Restore)

Для **Management-кластера** (самого Rancher Server) используется официальный пакет **`rancher-backup`** (основан на Velero). Он создаёт снимок state Rancher (etcd management-кластера + ресурсы Rancher) в совместимое хранилище — например, **S3** совместимое или локальную папку. Подробности о стратегиях etcd и general k8s backup — в [Стратегии резервного копирования etcd](../../etcd/backup_strategies.md) и [Backup-стратегии Kubernetes](../Operations/backup-strategies.md).

```bash
# 1. Установить rancher-backup (Apps & Marketplace → rancher-backup) в cattle-resources-system
# 2. Создать Backup CR с указанием хранилища
cat <<EOF | kubectl apply -f -
apiVersion: resources.cattle.io/v1
kind: Backup
metadata:
  name: daily-backup
spec:
  storageLocationName: s3-backup
serviceAccountName: rancher-backup  # SA с правами на снапшот etcd/management
EOF

# 3. Проверить статус
kubectl get backup
# →  COMPLETED/Completed
```

**Восстановление:**
```bash
apiVersion: resources.cattle.io/v1
kind: Restore
metadata:
  name: daily-restore
spec:
  backupFilename: daily-backup-xxxxx
```
→ Выполняется через UI (Cluster Management → Snapshot → Restore) или CR `Restore`. При восстановлении кластер останавливается, etcd переинициализируется.

> **Предупреждение:** восстановление — деструктивная операция. Перед восстановлением делайте резервную копию текущего состояния. Откат после неудачного апгрейда выполняется только через Restore из бэкапа предыдущей версии.

### Установка в air-gapped (изолированной) среде

При отсутствии доступа к интернету Rancher устанавливается из локального registry (harbor/registry mirror). Ключевые шаги:

1.  Создайте образы Rancher (`rancher-images.txt`) и загрузите их в приватный registry (используется скрипт `rancher-save-images.sh` / `rancher-load-images.sh`).
2.  Настройте `containerd`/regs для использования приватного registry: `/etc/rancher/rke2/registries.yaml` на узлах.
3.  Установите `rancher` с `--set rancherImage=registry.example.com/rancher/rancher` (и дополнительные `--set` для каталога system charts).
4.  Для исчерпывающего списка образов используйте `rancher-images-linux.txt` из дистрибутива релиза.

> Настройка приватного registry для K3s/RKE2 описывается в k3s-документации, а образы и процедура — в официальном руководстве по air-gapped. Для репозитория изображений используйте раздел Docker/`registry` (например, Harbor).

### Отключение / удаление Rancher (Cleanup)

```bash
# Удаление Helm-релиза (не удаляет CRD и не все ресурсы)
helm uninstall rancher -n cattle-system
```

> **Важно:** `helm uninstall` **не** удаляет все ресурсы `cattle-system` (например, `bootstrap-secret` и custom resources `*.cattle.io` остаются, особенно при наличии finalizer). Для полного развёртывания заново в существующем кластере удалите оставшиеся ресурсы/CRD:
> ```bash
> kubectl get crd | grep cattle.io
> kubectl delete crd <перечисленные CRD>   # осторожно: удаляет все Rancher-ресурсы
> ```
> В противном случае повторная установка может использовать устаревший `bootstrap-secret`, и заданный пароль не будет применён.

## Диагностика и устранение неполадок

### Проблема с bootstrap-паролем (12+ символов)

**Симптом:** заданный `bootstrapPassword` не подходит при входе, хотя в Secret записано правильное значение.

**Причины и решения:**
*   **Пароль короче 12 символов.** Rancher может не принять его и сгенерировать случайный. Используйте пароль длиной **≥12 символов**.
*   **Повторная установка в том же кластере.** Старый `bootstrap-secret` (и `users.management.cattle.io`) пережили `helm uninstall`. Удалите остаточные ресурсы (см. выше) либо верните прежний пароль.
*   **Ручное создание `bootstrap-secret` с неверной структурой** — Rancher заменит значение сгенерированным.

**Проверка:**
```bash
kubectl get secret -n cattle-system bootstrap-secret -o yaml
kubectl exec -it deploy/rancher -n cattle-system -- env | grep CATTLE_BOOTSTRAP_PASSWORD
```

### UI недоступен, но кластеры работают

*   Проверьте Ingress: `kubectl -n cattle-system get ingress`.
*   Проверьте, что Load Balancer направляет 443 на все узлы и DNS FQDN корректен: `curl -vk https://rancher.example.com/v3 -o /dev/null -w '%{http_code}'`.
*   Смотрите логи: `kubectl -n cattle-system logs -l app=rancher --tail=100`.

### Установка не может выпустить TLS-сертификат (cert-manager)

**Симптом:** Account/Order в `challenges` застрял; Ingress в состоянии `Unavailable`.

**Причины:**
*   cert-manager не установлен / CRDs не установлены (`--set installCRDs=true`).
*   Для HTTP-01 (Let's Encrypt) порт 80 недоступен снаружи или FQDN не резолвится.
*   `letsEncrypt.email` не задан.

**Решение:**
```bash
kubectl -n cert-manager get pods          # все Running
kubectl -n cattle-system get certificate  # Observe → Ready
kubectl -n cattle-system logs -l app=rancher --tail=50 | grep -i "certificate\|acme"
```

### Ошибка kubectl: API Aggregation Layer

Если кластер управления не имеет включённой API Aggregation Layer (не RKE2/K3s), Rancher не сможет зарегистрировать extension API server. Для RKE2/K3s он включается автоматически; для кастомных кластеров — убедитесь в его активации.

### Ошибка re-install: устаревшие ресурсы в кластере

При повторной установке в тот же кластер возможна ошибка из-за остатков (finalizers, `*.cattle.io` CR, старые webhook). Очистите namespace/CRD согласно разделу Cleanup, либо используйте свежий кластер.

### firewalld / CNI

Если `firewalld` включён на узлах — отключите его, т.к. он несовместим с CNI (canal/flannel):
```bash
systemctl disable --now firewalld
```

## Дополнительная информация

### Жизненный цикл и миграция

*   **RKE1:** поддержка прекращена в июле 2025 года. Новые инсталляции на RKE1 запрещены. Rancher 2.12+ не поддерживает провижининг/управление RKE1 — мигрируйте на RKE2.
*   **Backup:** используйте пакет `rancher-backup` (основан на Velero) для регулярного создания снимков состояния Management-кластера в S3 (см. раздел «Резервное копирование»).

### Лучшие практики эксплуатации

*   **Управление паролем admin:** узнайте постоянный admin-пароль после первого входа; bootstrap-пароль временный и хранится в Secret/логах — не используйте его повторно в production.
*   **Обновления:** следуйте supported upgrade path (последний патч → следующая minor); всегда делайте `rancher-backup` перед апгрейдом.
*   **Держите `cattle-system` изолированным** в `System Project` с ограниченным доступом (только Cluster Admins).
*   **Мониторинг Management-кластера:** наблюдайте за ресурсами (см. [Мониторинг в Rancher](./rancher_monitoring.md)) и etcd latency.
*   **Не меняйте `useBundledSystemChart` бездумно:** для air-gapped это обязательный флаг, для internet-окружения — по умолчанию `false`.
*   **Сохраняйте `--set` параметры** (например, в файле `values.yaml`), чтобы использовать их при апгрейдах/переустановках.

### Связанные темы

* [Rancher: Обзор платформы](./rancher_overview.md) — архитектура и управление.
* [Управление пользователями и RBAC](./rancher_rbac.md) — настройка после установки.
* [RKE в Rancher](./rancher_rke.md) — детали работы RKE2, snapshots, etcd.
* [Установка cert-manager](../ToolsUtilities/cert_manager/installation.md) — полное руководство.
* [Мониторинг в Rancher](./rancher_monitoring.md) — observability Management/Downstream кластеров.

**Внешние ресурсы:**

* [Rancher Installation Guide (Official)](https://ranchermanager.docs.rancher.com/getting-started/installation-and-upgrade)
* [RKE2 Documentation](https://docs.rke2.io/)
* [Rancher Helm Chart Options](https://ranchermanager.docs.rancher.com/getting-started/installation-and-upgrade/installation-references/helm-chart-options)
