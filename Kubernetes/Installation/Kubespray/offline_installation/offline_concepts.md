# Kubespray: Offline установка — Основные концепции

## Принципы offline-развертывания

Offline-установка Kubernetes через Kubespray требует предварительной загрузки всех артефактов на машине с доступом в интернет и последующей их передачи в закрытый контур.

### Ключевые отличия от online-установки

| Аспект | Online | Offline |
| :--- | :--- | :--- |
| **Доступ к интернету** | Требуется на всех узлах | Не требуется |
| **Загрузка образов** | Автоматически из registry | Предварительная загрузка в Harbor |
| **Python зависимости** | `pip install` на узле | Перенос venv архивом |
| **Helm чарты** | `helm pull` | Локальный OCI registry |
| **Время установки** | 15-30 мин | 15-30 мин (после подготовки) |
| **Подготовка** | Минимальная | 1-2 часа на машине с inet |

## Этапы offline-установки

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

## Требования к инфраструктуре

### Минимальная конфигурация

| Роль | CPU | RAM | SSD | ОС | Пример IP |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **pc-inet** | 2 | 4GB | 20GB | Ubuntu 24.04 | 192.168.1.99 |
| **harbor** | 2 | 4GB | 50GB | Ubuntu 24.04 | 192.168.1.100 |
| **master-1** | 2 | 4GB | 50GB | Ubuntu 24.04 | 192.168.1.101 |
| **master-2** | 2 | 4GB | 50GB | Ubuntu 24.04 | 192.168.1.102 |
| **master-3** | 2 | 4GB | 50GB | Ubuntu 24.04 | 192.168.1.103 |
| **node-1** | 4 | 8GB | 100GB | Ubuntu 24.04 | 192.168.1.104 |
| **node-2** | 4 | 8GB | 100GB | Ubuntu 24.04 | 192.168.1.105 |
| **MetalLB VIP** | - | - | - | - | 192.168.1.200 |

### Предварительные требования

1. **SSH доступ:** master-1 должен иметь доступ ко всем узлам по SSH с sudo правами
2. **Harbor:** Настроенный HTTPS реестр в закрытом контуре
3. **Сеть:** Все узлы в одной подсети, свободный IP для MetalLB
4. **Пользователь:** root или пользователь с беспарольным sudo (например, `admin`)

## Выбор компонентов

### Container Runtime: containerd vs CRI-O

| Критерий | containerd | CRI-O |
| :--- | :--- | :--- |
| **По умолчанию в Kubespray** | ✅ Да | ❌ Нет |
| **Оффлайн-режим** | Лучше тестируется | Требует ручных правок |
| **Зависимости ОС** | Минимум | Больше |
| **Интеграция с K8s** | Полная | Tight (OpenShift) |
| **Рекомендация** | **Выбран для гайда** | Альтернатива |

### CNI плагин: Cilium

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

### Балансировщик: MetalLB

Для bare-metal кластеров без облачного провайдера:

```yaml
metallb_enabled: true
```

Дополнительно см. [MetalLB](../../../Networking/metallb.md).

## Конфигурация Kubespray для offline

### Переменные offline-режима

Файл: `group_vars/all/offline.yml`

```yaml
---
download_run_once: true           # Загрузка на один узел
download_localhost: true          # Загрузка на localhost (pc-inet)
download_keep_remote_cache: true  # Сохранение кэша
download_force_cache: true        # Принудительное использование кэша
download_cache_dir: /opt/kubespray-cache  # Директория кэша
```

### Настройка для Harbor

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

### Аутентификация containerd

Файл: `group_vars/all/containerd.yml`

```yaml
containerd_registry_auth:
  - registry: harbor.domain.local
    prefix: harbor.domain.local
    username: admin
    password: <password_ot_harbor>
```

> **Важно:** Проект `k8s` в Harbor должен быть **публичным**, так как containerd не считывает логин/пароль из конфига автоматически.

## Отключение проверки digest образов

При загрузке в Harbor SHA образов изменяется. Необходимо отключить проверку digest для Cilium:

Файл: `group_vars/k8s_cluster/k8s-net-cilium.yml`

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

## Связанные документы

- **[Определения](./offline_definitions.md)** — базовые термины
- **[Практические сценарии](./offline_practical.md)** — обзор этапов
- **[Шаг 1: Подготовка VM](./step1_vm_preparation.md)** — подготовка серверов
- **[Шаг 2: Подготовка с интернетом](./step2_internet_env.md)** — загрузка артефактов
- **[Шаг 3: Подготовка закрытого контура](./step3_offline_env.md)** — загрузка в Harbor
- **[Шаг 4: Развертывание кластера](./step4_cluster_deploy.md)** — установка Kubernetes
- **[Шаг 5: MetalLB и Ingress](./step5_metallb_ingress.md)** — настройка LoadBalancer
- **[Troubleshooting](./troubleshooting.md)** — решение проблем
- **[Kubespray: Обзор](../overview.md)** — общая информация
- **[Harbor: Установка](../../../../Docker/Docker_registries/Harbor/installation.md)** — развертывание Harbor
- **[MetalLB](../../../Networking/metallb.md)** — настройка балансировщика

---

*Этот файл является частью декомпозированной документации по offline-установке Kubespray.*
