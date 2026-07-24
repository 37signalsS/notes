# Kubespray: Offline установка — Основные концепции

## Определения

Базовые термины offline-режима (Air-gapped, закрытый контур, артефакты) подробно описаны в разделе **[Kubespray: Offline установка — Определения](./offline_definitions.md)**.

---

## Основные концепции

### Принципы offline-развёртывания

Основная концепция — **полная изоляция**. Целевые узлы не должны выполнять DNS-запросы к публичным серверам или пытаться достучаться до `gcr.io/docker.io` даже при наличии прокси. Все запросы перехватываются и перенаправляются на локальный Harbor.

#### Почему containerd?

Для офлайн-инсталляций **containerd** является предпочтительным runtime из-за:
1. **Децентрализованной конфигурации:** использование `hosts.toml` для каждого реестра позволяет гибко перенаправлять `docker.io` на `harbor.local/k8s/docker.io` без глобальных правок `config.toml`.
2. **Низкого оверхеда:** отсутствие необходимости в Docker Daemon упрощает диагностику в условиях закрытого контура.
3. **Совместимости:** Kubespray имеет наиболее отлаженные Ansible-роли именно для containerd в Air-gapped режиме.

#### Почему Cilium?

Cilium заменяет `kube-proxy` (через `kube-proxy-replacement`), что упрощает сетевую архитектуру и позволяет избежать проблем с `iptables` в сложных сетевых сегментах.

**Требуемые параметры (group_vars):**
```yaml
kube_network_plugin: cilium
cilium_version: "v1.19.6"
cilium_kube_proxy_replacement: true
cilium_install_with_helm: true # Обязательно для OCI в Harbor
cilium_deploy_with_digest: false # Игнорирование SHA-хеша при миграции
```

---

## Практические сценарии

### Справочник переменных для offline-режима

Все настройки вносятся в файл `inventory/offline_cluster/group_vars/all/offline.yml`.

#### 1. Глобальные настройки кэширования (на pc-inet)
```yaml
# Оптимизация процесса загрузки
download_run_once: true           # Скачивать файл/образ только один раз
download_localhost: true          # Хранить кэш на управляющей машине
local_release_dir: "/opt/kubespray-releases" # Путь для бинарных файлов
download_cache_dir: "/opt/kubespray-cache"     # Путь для tar-архивов образов
```

#### 2. Переопределение реестров (в закрытом контуре)
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

#### 3. Настройка авторизации (если проект k8s не Public)
Если вы решили сделать проект приватным, добавьте в `group_vars/all/containerd.yml`:
```yaml
containerd_registry_auth:
  - registry: harbor.domain.local
    prefix: harbor.domain.local
    username: admin
    password: <secure_password>
```

---

## Дополнительная информация

### Важные нюансы эксплуатации

- **Отключение Digest:** При миграции через `docker save/load` и последующий push в Harbor, оригинальный digest образа может измениться. Без `cilium_deploy_with_digest: false` поды Cilium не запустятся, так как `containerd` будет искать образ по старому хешу.
- **MTU:** В виртуальных средах (VMware/Proxmox) рекомендуется устанавливать `cilium_mtu: 1450`, чтобы избежать фрагментации пакетов при инкапсуляции VXLAN/Geneve.

### См. также

- **[Шаг 3: Подготовка закрытого контура](./step3_offline_env.md)** — настройка Harbor и импорт образов.
- **[Troubleshooting](./troubleshooting.md)** — решение проблем с Digest и SSL.
