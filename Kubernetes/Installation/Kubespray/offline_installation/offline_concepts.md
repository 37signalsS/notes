# Kubespray: Offline установка — Основные концепции

## Определения

**Контроллер реестра (Registry Controller)** — компонент containerd,負責解析 имён образов и перенаправление pull-запросов на указанные эндпоинты. В offline-среде контроллер реестра — единственная точка взаимодействия между containerd и Harbor. Он определяет, какой реестр использовать для каждого префикса имени образа, и применяет параметры TLS/авторизации из конфигурационных файлов.

**hosts.toml** — система конфигурации registry-контроллера containerd (версия 1.5+). Каждый реестр получает отдельный файл `/etc/containerd/certs.d/<registry>/hosts.toml`, что позволяет настраивать зеркала, TLS и авторизацию без глобальных правок `config.toml` и без перезагрузки демона.

**Реестровый маппинг (Registry Mapping)** — механизм перенаправления публичных реестров (docker.io, gcr.io, quay.io) на локальный Harbor. Формируется переменными `*_image_repo` в `group_vars/all/offline.yml` и определяет, куда containerd будет обращаться при pull-запросах к образам из различных источников.

**Кэш артефактов (Download Cache)** — локальная директория на pc-inet (`/opt/kubespray-cache`), куда Kubespray сохраняет tar-архивы образов и бинарные файлы при первичной загрузке. Кэш используется для формирования переносимых архивов и предотвращает повторные обращения к публичным реестрам.

Базовые термины offline-режима (Air-gapped, закрытый контур, артефакты) подробно описаны в разделе **[Kubespray: Offline установка — Определения](./offline_definitions.md)**.

---

## Основные концепции

### Принципы offline-развёртывания

Основная концепция — **полная изоляция**. Целевые узлы не должны выполнять DNS-запросы к публичным серверам или пытаться достучаться до `gcr.io/docker.io` даже при наличии прокси. Все запросы перехватываются и перенаправляются на локальный Harbor.

Механизм перехвата работает на двух уровнях:
1. **На уровне containerd:** файлы `hosts.toml` перенаправляют все pull-запросы на Harbor.
2. **На уровне Ansible:** переменные `*_image_repo` формируют теги образов в формате `harbor.domain.local/k8s/<оригинальный_путь>`, что гарантирует, что Kubespray никогда не обратится к публичным реестрам.

### Почему containerd?

Для офлайн-инсталляций **containerd** является предпочтительным runtime из-за:
1. **Децентрализованной конфигурации:** использование `hosts.toml` для каждого реестра позволяет гибко перенаправлять `docker.io` на `harbor.local/k8s/docker.io` без глобальных правок `config.toml`.
2. **Низкого оверхеда:** отсутствие необходимости в Docker Daemon упрощает диагностику в условиях закрытого контура.
3. **Совместимости:** Kubespray имеет наиболее отлаженные Ansible-роли именно для containerd в Air-gapped режиме.
4. **Простоты отладки:** наличие `crictl` и `nerdctl` позволяет быстро проверить доступность образов и состояние контейнеров на конкретном узле.

#### Архитектура containerd в offline-режиме

В стандартной конфигурации containerd взаимодействует с публичными реестрами напрямую. В offline-среде эта связь должна быть полностью перенацелена:

```text
kubelet → containerd (CRI) → registry controller → /etc/containerd/certs.d/
                                                           ↓
                                              ┌─────────────────────────┐
                                              │  docker.io/...          │ → harbor.domain.local/k8s/docker.io/...
                                              │  gcr.io/...             │ → harbor.domain.local/k8s/gcr.io/...
                                              │  quay.io/...            │ → harbor.domain.local/k8s/quay.io/...
                                              │  harbor.domain.local/...│ → harbor.domain.local/... (без маппинга)
                                              └─────────────────────────┘
```

Для работы containerd в offline-режиме необходимо:
1. Включить `config_path` в конфигурации registry.
2. Создать файлы `hosts.toml` для каждого перенаправляемого реестра.
3. Убедиться, что CA-сертификат Harbor добавлен в доверенное хранилище узла.

### Почему Cilium?

Cilium заменяет `kube-proxy` (через `kube-proxy-replacement`), что упрощает сетевую архитектуру и позволяет избежать проблем с `iptables` в сложных сетевых сегментах.

**Преимущества Cilium в offline-среде:**
- **eBPF-ный datapath:** отсутствие зависимости от `iptables` исключает проблемы с конфликтами правил фаервола.
- **Встроенный Hubble:**提供 сетевую видимость без дополнительных компонентов.
- **Helm-based установка:** OCI-формат чарта позволяет хранить его в Harbor и устанавливать через стандартный Helm-контроллер.

**Требуемые параметры (group_vars):**
```yaml
kube_network_plugin: cilium
cilium_version: "v1.19.6"
cilium_kube_proxy_replacement: true
cilium_install_with_helm: true # Обязательно для OCI в Harbor
cilium_deploy_with_digest: false # Игнорирование SHA-хеша при миграции
```

#### Механизм digest и почему его отключают

Kubespray по умолчанию прописывает digest (SHA-хеш) для образов Cilium в Ansible-ролях. Digest гарантирует, что устанавливается точная копия образа. Однако при миграции через `docker save/load` и последующий push в Harbor оригинальный digest образа может измениться из-за пересоздания слоёв и метаданных. Без отключения digest (`cilium_deploy_with_digest: false`) containerd будет пытаться найти образ по старому хешу и завершит работу с ошибкой `manifest unknown`.

### Структура group_vars для offline-режима

Конфигурация offline-режима распределена по нескольким файлам в `inventory/offline_cluster/group_vars/`:

| Файл | Назначение | Ключевые переменные |
| :--- | :--- | :--- |
| `all/offline.yml` | Глобальные настройки кэширования и реестра | `download_run_once`, `registry_host`, `*_image_repo` |
| `all/containerd.yml` | Авторизация в Harbor | `containerd_registry_auth` |
| `k8s_cluster/k8s-net-cilium.yml` | Сетевые параметры Cilium | `cilium_mtu`, `cilium_tunnel_mode` |
| `k8s_cluster/k8s.yml` | Основные настройки кластера | `kube_version`, `kube_network_plugin` |

---

## Практические сценарии

### 1. Справочник переменных для offline-режима

Все настройки вносятся в файл `inventory/offline_cluster/group_vars/all/offline.yml`.

#### 1.1 Глобальные настройки кэширования (на pc-inet)
```yaml
# Оптимизация процесса загрузки
download_run_once: true           # Скачивать файл/образ только один раз
download_localhost: true          # Хранить кэш на управляющей машине
download_format: "tarball"        # Формат архивов для переноса
local_release_dir: "/opt/kubespray-releases" # Путь для бинарных файлов
download_cache_dir: "/opt/kubespray-cache"     # Путь для tar-архивов образов
```

**Параметры объяснены:**
- `download_run_once: true` — при установке на pc-inet образы скачиваются только один раз, а не на каждый узел. Это критично в offline-среде, где повторная загрузка невозможна.
- `download_localhost: true` — бинарные файлы и образы сохраняются локально на pc-inet, а не на целевых узлах. Это позволяет упаковать их в единый архив для переноса.
- `download_format: "tarball"` — образы сохраняются в формате `.tar`, что упрощает ручную загрузку в Harbor через `docker load` и `docker push`.

#### 1.2 Переопределение реестров (в закрытом контуре)
```yaml
registry_host: "harbor.domain.local"

# Маппинг публичных реестров на локальный проект k8s
kube_image_repo: "{{ registry_host }}/k8s/registry.k8s.io"
gcr_image_repo: "{{ registry_host }}/k8s/gcr.io"
docker_image_repo: "{{ registry_host }}/k8s/docker.io"
quay_image_repo: "{{ registry_host }}/k8s/quay.io"

# Настройка Cilium для работы через локальный OCI
cilium_install_extra_flags: "--repository oci://{{registry_host}}/helm/cilium"
```

**Как работает маппинг:**
Переменная `kube_image_repo` определяет префикс для всех образов Kubernetes. Когда Kubespray формирует тег образа, он подставляет `{{ registry_host }}/k8s/` вместо `registry.k8s.io/`. В результате образ `kube-apiserver:v1.34.3` получает тег `harbor.domain.local/k8s/registry.k8s.io/kube-apiserver:v1.34.3`. Containerd на целевом узле через `hosts.toml` перенаправляет этот запрос в Harbor.

#### 1.3 Настройка авторизации (если проект k8s не Public)
Если вы решили сделать проект приватным, добавьте в `group_vars/all/containerd.yml`:
```yaml
containerd_registry_auth:
  - registry: harbor.domain.local
    prefix: harbor.domain.local
    username: admin
    password: <secure_password>
```

**Важно:** Проект `k8s` в Harbor должен быть Public на этапе первоначальной установки, чтобы containerd мог загружать образы до момента настройки секретов аутентификации. После завершения установки проект можно сделать приватным.

### 2. Конфигурация containerd для offline-реестра

В offline-среде containerd должен перенаправлять pull-запросы на Harbor через файлы `hosts.toml`. Kubespray автоматизирует эту настройку, но понимание механизма критично для диагностики.

#### 2.1 Включение config_path в containerd

Убедитесь, что в `/etc/containerd/config.toml` включён параметр `config_path`:

```toml
[plugins."io.containerd.grpc.v1.cri".registry]
  config_path = "/etc/containerd/certs.d"
```

Это告诉 containerd искать конфигурацию реестров в директории `/etc/containerd/certs.d/`. Без этого параметра файлы `hosts.toml` игнорируются.

#### 2.2 Файл hosts.toml для Harbor

Создайте файл `/etc/containerd/certs.d/harbor.domain.local/hosts.toml`:

```toml
# /etc/containerd/certs.d/harbor.domain.local/hosts.toml
server = "https://harbor.domain.local"

[host."https://harbor.domain.local"]
  capabilities = ["pull", "resolve"]
  ca = "/usr/local/share/ca-certificates/harbor-ca.crt"
  skip_verify = false
```

**Параметры:**
- `server` — базовый URL реестра. Containerd использует его для формирования API-запросов.
- `capabilities` — разрешённые операции: `pull` (загрузка образов), `resolve` (резолвинг тегов в digest).
- `ca` — путь к CA-сертификату Harbor. Если Harbor использует самоподписанный сертификат, этот параметр обязателен.
- `skip_verify` — отключение проверки TLS (не рекомендуется, но упрощает отладку).

#### 2.3 Файл hosts.toml для перенаправления docker.io

Создайте файл `/etc/containerd/certs.d/docker.io/hosts.toml`:

```toml
# /etc/containerd/certs.d/docker.io/hosts.toml
server = "https://docker.io"

[host."https://harbor.domain.local"]
  capabilities = ["pull", "resolve"]
  ca = "/usr/local/share/ca-certificates/harbor-ca.crt"

[host."https://docker.io"]
  capabilities = ["pull", "resolve"]
```

**Логика:** при pull-запросе к `docker.io/library/nginx:latest` containerd сначала попытается загрузить образ из Harbor (`harbor.domain.local/k8s/docker.io/library/nginx:latest`). Если образ не найден — обратится к оригинальному реестру (в offline-среде это невозможно, но конфигурация остаётся для совместимости).

#### 2.4 Проверка конфигурации

После настройки перезапустите containerd и проверьте корректность:

```bash
# Перезапуск containerd
sudo systemctl restart containerd

# Проверка конфигурации registry
sudo containerd config dump | grep -A10 "registry.mirrors"
# → [plugins."io.containerd.grpc.v1.cri".registry.mirrors."docker.io"]
# →   endpoint = ["https://harbor.domain.local"]

# Проверка доступности Harbor
sudo crictl pull harbor.domain.local/k8s/registry.k8s.io/pause:3.10
# → Image is up to date for harbor.domain.local/k8s/registry.k8s.io/pause:3.10
```

### 3. Публикация Helm-чарта Cilium в Harbor

Для установки Cilium через Helm в offline-среде чарт должен быть доступен в OCI-репозитории Harbor.

#### 3.1 Загрузка чарта на pc-inet

```bash
# Добавление официального репозитория Cilium
helm repo add cilium https://helm.cilium.io
helm repo update

# Скачивание чарта
helm pull cilium/cilium --version 1.19.6
# → /opt/kuber_off/kubespray/cilium-1.19.6.tgz

# Перемещение в директорию релизов
mv cilium-1.19.6.tgz /opt/kubespray-releases/
```

#### 3.2 Публикация в Harbor (на master-1)

```bash
# Авторизация в Harbor
helm registry login harbor.domain.local
# → Login Succeeded

# Публикация в OCI-репозиторий
helm push /opt/kubespray-releases/cilium-1.19.6.tgz oci://harbor.domain.local/helm
# → Pushed: harbor.domain.local/helm/cilium:1.19.6
# → Digest: sha256:xxxx...
```

#### 3.3 Проверка доступности чарта

```bash
# Поиск чарта в OCI-репозитории
helm search oci://harbor.domain.local/helm/cilium --version 1.19.6
# → NAME                CHART VERSION   APP VERSION     DESCRIPTION
# → harbor.domain.local/helm/cilium   1.19.6          1.19.6          Cilium is a networking, observability...
```

### 4. Цепочка信任 (Trust Chain) для Harbor

В offline-среде каждый узел кластера должен доверять CA, подписавшему сертификат Harbor. Это критично для работы containerd и kubelet.

#### 4.1 Установка CA-сертификата на все узлы

```bash
# Копирование сертификата на каждый узел
for node in master-{1,2,3} node-{1,2}; do
  scp harbor-ca.crt admin@$node:/tmp/
  ssh admin@$node "sudo cp /tmp/harbor-ca.crt /usr/local/share/ca-certificates/harbor-ca.crt && sudo update-ca-certificates"
done
```

#### 4.2 Проверка доверия

```bash
# Проверка на конкретном узле
openssl s_client -connect harbor.domain.local:443 </dev/null 2>/dev/null | openssl x509 -noout -subject
# → subject=CN = harbor.domain.local

# Проверка через containerd
sudo crictl pull harbor.domain.local/k8s/registry.k8s.io/pause:3.10
```

### 5. DNS-конфигурация для offline-реестра

Все узлы кластера должны разрешать имя Harbor. В offline-среде нет доступа к публичным DNS-серверам, поэтому необходимо настроить локальный DNS или добавить записи в `/etc/hosts`.

#### 5.1 Вариант 1: записи в /etc/hosts (простой)

```bash
# Добавление на каждый узел
echo "192.168.1.100 harbor.domain.local" | sudo tee -a /etc/hosts
```

#### 5.2 Вариант 2: локальный DNS-сервер (рекомендуется)

Если в закрытом контуре есть DNS-сервер (например, BIND или dnsmasq), добавьте запись:

```
# Zone: domain.local
harbor  IN  A  192.168.1.100
```

#### 5.3 Проверка DNS

```bash
# Резолвинг имени Harbor
nslookup harbor.domain.local
# → Address: 192.168.1.100

# Проверка доступности API Harbor
curl -sk https://harbor.domain.local/api/v2.0/health
# → {"status":"healthy"}
```

---

## Дополнительная информация

### Важные нюансы эксплуатации

- **Отключение Digest:** При миграции через `docker save/load` и последующий push в Harbor, оригинальный digest образа может измениться. Без `cilium_deploy_with_digest: false` поды Cilium не запустятся, так как `containerd` будет искать образ по старому хешу. Digest отключается для всех трёх компонентов Cilium:
  ```yaml
  cilium_deploy_with_digest: false
  hubble_ui_deploy_with_digest: false
  cilium_operator_deploy_with_digest: false
  ```

- **MTU:** В виртуальных средах (VMware/Proxmox) рекомендуется устанавливать `cilium_mtu: 1450`, чтобы избежать фрагментации пакетов при инкапсуляции VXLAN/Geneve. Заголовки инкапсуляции добавляют 50-70 байт, что при MTU 1500 на физическом интерфейсе превышает максимальный размер пакета.

- **SystemdCgroup:** В современных дистрибутивах (Ubuntu 22.04+) 반드시 установите `SystemdCgroup = true` в конфигурации containerd. Несоответствие этого параметра вызывает нестабильность kubelet и циклические перезапуски подов.

- **Версионирование:** Версии Kubespray, Kubernetes и Cilium должны соответствовать матрице совместимости. Использование несовместимых версий приводит к ошибкам на этапе установки или нестабильности кластера.

### Типовые ошибки конфигурации

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `x509: certificate signed by unknown authority` | CA-сертификат Harbor не установлен на узле | Добавить сертификат в `/usr/local/share/ca-certificates/` и выполнить `update-ca-certificates` |
| `manifest unknown` | Образ отсутствует в Harbor или указан неверный тег | Проверить наличие образа в веб-интерфейсе Harbor |
| `connection refused` | Harbor недоступен (DNS, порт, сервис) | Проверить DNS-разрешение, доступность порта 443, статус сервиса Harbor |
| `no such host` | Имя Harbor не резолвится | Добавить запись в `/etc/hosts` или настроить DNS |
| Cilium `ImagePullBackOff` | Digest не совпадает после миграции | Установить `cilium_deploy_with_digest: false` в offline.yml |

### См. также

- **[Шаг 3: Подготовка закрытого контура](./step3_offline_env.md)** — настройка Harbor и импорт образов.
- **[Troubleshooting](./troubleshooting.md)** — решение проблем с Digest и SSL.
