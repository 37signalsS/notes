# Kubespray: Offline установка — Основные концепции

## Определения

**Offline-кластер (Air-gapped)** — кластер Kubernetes, развёртываемый в изолированной среде без доступа к интернету, где все артефакты предварительно загружаются и доставляются в закрытый контур.

**Закрытый контур** — изолированная сеть без прямого доступа к интернету, требующая локальных реестров образов (Harbor) и зеркал пакетов.

**Артефакты Kubespray** — бинарные файлы Kubernetes, образы контейнеров, Helm-чарты и Python-зависимости, необходимые для установки кластера.

---

## Основные концепции

### Принципы offline-развертывания

Offline-установка Kubernetes через Kubespray требует предварительной загрузки всех артефактов на машине с доступом в интернет и последующей их передачи в закрытый контур.

#### Ключевые отличия от online-установки

| Аспект | Online | Offline |
| :--- | :--- | :--- |
| **Доступ к интернету** | Требуется на всех узлах | Не требуется |
| **Загрузка образов** | Автоматически из registry | Предварительная загрузка в Harbor |
| **Python зависимости** | `pip install` на узле | Перенос venv архивом |
| **Helm чарты** | `helm pull` | Локальный OCI registry |
| **Время установки** | 15-30 мин | 15-30 мин (после подготовки) |
| **Подготовка** | Минимальная | 1-2 часа на машине с интернетом |

#### Этапы offline-установки

```
┌─────────────────────────────────────────────────────────────┐
│ Этап 1: Подготовка артефактов (машина с интернетом)         │
├─────────────────────────────────────────────────────────────┤
│ 1. Клонирование Kubespray                                   │
│ 2. Настройка inventory для download                         │
│ 3. Загрузка Python зависимостей                             │
│ 4. Загрузка образов контейнеров                             │
│ 5. Загрузка Helm чартов                                     │
│ 6. Упаковка в архивы                                        │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ Этап 2: Подготовка закрытого контура                        │
├─────────────────────────────────────────────────────────────┤
│ 1. Распаковка архивов на master-1                           │
│ 2. Развертывание Harbor                                     │
│ 3. Загрузка образов в Harbor                                │
│ 4. Настройка inventory для offline                          │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ Этап 3: Развертывание кластера                              │
├─────────────────────────────────────────────────────────────┤
│ 1. Запуск ansible-playbook cluster.yml                      │
│ 2. Проверка кластера                                        │
│ 3. Настройка MetalLB и Ingress                              │
└─────────────────────────────────────────────────────────────┘
```

### Выбор компонентов

#### Container Runtime: containerd vs CRI-O

| Критерий | containerd | CRI-O |
| :--- | :--- | :--- |
| **По умолчанию в Kubespray** | ✅ Да | ❌ Нет |
| **Оффлайн-режим** | Лучше тестируется | Требует ручных правок |
| **Зависимости ОС** | Минимум | Больше |
| **Интеграция с K8s** | Полная | Tight (OpenShift) |
| **Рекомендация** | **Выбран для гайда** | Альтернатива |

#### CNI плагин: Cilium

**Выбор Cilium обусловлен:**

- Поддержка eBPF для высокой производительности
- Встроенная наблюдаемость через Hubble
- Продвинутые политики безопасности
- Замена kube-proxy (kube-proxy replacement)

**Требуемые настройки:**

```yaml
kube_network_plugin: cilium
cilium_version: "1.18.5"
cilium_kube_proxy_replacement: true
cilium_tunnel_mode: geneve  # Для VMware
cilium_mtu: "1450"
```

#### Балансировщик: MetalLB

Для bare-metal кластеров без облачного провайдера:

```yaml
metallb_enabled: true
```

Подробнее о MetalLB — в [документации по балансировщику](../../../Networking/metallb.md).

---

## Практические сценарии

### Требования к инфраструктуре

Информация о минимальной конфигурации VM и предварительных требованиях приведена в [практических сценариях offline-установки](./offline_practical.md#Инфраструктура).

---

## Дополнительная информация

### Справочник конфигураций Kubespray

#### Переменные offline-режима

Файл: `group_vars/all/offline.yml`

```yaml
---
download_run_once: true           # Загрузка на один узел
download_localhost: true          # Загрузка на localhost (pc-inet)
download_keep_remote_cache: true  # Сохранение кэша
download_force_cache: true        # Принудительное использование кэша
download_cache_dir: /opt/kubespray-cache  # Директория кэша
```

#### Настройка для Harbor

Файл: `group_vars/all/offline.yml`

```yaml
registry_host: "harbor.domain.local"
kube_image_repo: "{{ registry_host }}/k8s/registry.k8s.io"
gcr_image_repo: "{{ registry_host }}/k8s/gcr.io"
docker_image_repo: "{{ registry_host }}/k8s/docker.io"
quay_image_repo: "{{ registry_host }}/k8s/quay.io"

# Для Cilium через OCI
cilium_install_extra_flags: "--repository oci://{{registry_host}}/helm/cilium"
```

#### Аутентификация containerd

Файл: `group_vars/all/containerd.yml`

```yaml
containerd_registry_auth:
  - registry: harbor.domain.local
    prefix: harbor.domain.local
    username: admin
    password: <password_ot_harbor>
```

> **Важно:** Проект `k8s` в Harbor должен быть **публичным**, так как containerd не считывает логин/пароль из конфига автоматически.

### Отключение проверки digest образов

При загрузке в Harbor SHA образов изменяется. Необходимо отключить проверку digest для Cilium в файле `group_vars/k8s_cluster/k8s-net-cilium.yml`:

```yaml
cilium_extra_values:
  image:
    useDigest: false
    digest: ""
  operator:
    image:
      useDigest: false
      digest: ""
  envoy:
    image:
      useDigest: false
      digest: ""
  hubble:
    relay:
      image:
        useDigest: false
        digest: ""
    ui:
      backend:
        image:
          useDigest: false
          digest: ""
      frontend:
        image:
          useDigest: false
          digest: ""
```

Эта конфигурация также описана в разделе [troubleshooting](./troubleshooting.md#Проблема-Cilium-image-с-SHA-digest).

### Связанные темы

Базовые термины — в [определениях offline-установки](./offline_definitions.md), обзор этапов — в [практических сценариях](./offline_practical.md). Детальные инструкции: [подготовка VM](./step1_vm_preparation.md), [загрузка артефактов](./step2_internet_env.md), [подготовка закрытого контура](./step3_offline_env.md), [развёртывание кластера](./step4_cluster_deploy.md), [настройка MetalLB и Ingress](./step5_metallb_ingress.md). Валидация — в [проверке кластера](./cluster_verification.md), решение проблем — в [troubleshooting](./troubleshooting.md), управление — в [post-install управлении](./post_install_management.md).

Общий обзор Kubespray — в [overview.md](../overview.md). Смежные темы: [Harbor](../../../../Docker/Docker_registries/Harbor/installation.md), [MetalLB](../../../Networking/metallb.md).
