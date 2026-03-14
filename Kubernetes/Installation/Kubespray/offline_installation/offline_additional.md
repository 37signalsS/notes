# Kubespray: Offline установка — Дополнительная информация

## Разделы дополнительной информации

Этот файл содержит указатель на тематические разделы дополнительной информации.

| Раздел | Файл | Описание |
| :--- | :--- | :--- |
| **Troubleshooting** | [troubleshooting.md](./troubleshooting.md) | Решение распространённых проблем |
| **Post-Install управление** | [post_install_management.md](./post_install_management.md) | Управление кластером после установки |
| **Проверка кластера** | [cluster_verification.md](./cluster_verification.md) | Валидация установки |

---

## Быстрая справка

### Работа с containerd

```bash
# Запущенные контейнеры
sudo crictl ps

# Запущенные поды на узле
sudo crictl pods

# Логи контейнера
sudo crictl logs <CONTAINER_ID>
```

### Управление через Kubespray

| Задача | Команда |
| :--- | :--- |
| **Добавить ноду** | `ansible-playbook -i inventory.ini scale.yml` |
| **Обновить k8s** | `ansible-playbook -i inventory.ini upgrade-cluster.yml` |
| **Изменить сеть** | `ansible-playbook -i inventory.ini cluster.yml --tags cilium` |

### Диагностика Cilium

```bash
# Статус кластера
kubectl -n kube-system exec -it ds/cilium -- cilium status

# Проверка здоровья
kubectl -n kube-system exec -it ds/cilium -- cilium health status

# Наблюдение за трафиком
kubectl -n kube-system exec -it ds/cilium -- hubble observe --follow
```

---

## Связанные документы

- **[Определения](./offline_definitions.md)** — базовые термины
- **[Основные концепции](./offline_concepts.md)** — принципы offline-установки
- **[Практические сценарии](./offline_practical.md)** — обзор этапов установки
- **[Troubleshooting](./troubleshooting.md)** — решение проблем
- **[Post-Install управление](./post_install_management.md)** — управление после установки
- **[Проверка кластера](./cluster_verification.md)** — валидация установки
- **[Kubespray: Обзор](../overview.md)** — общая информация
- **[Kubespray: Управление кластером](../cluster_management.md)** — масштабирование и обновление
- **[Harbor: Обзор](../../../../Docker/Docker_registries/Harbor/overview.md)** — реестр образов
- **[MetalLB](../../../Networking/metallb.md)** — балансировщик
- **[CNI и kube-proxy](../../../Networking/Network/CNI/definitions.md)** — сетевые плагины
- **[Air-gapped кластеры](../../../Troubleshooting/Common_Errors/PodImagePullErrors/airgapped.md)** — работа с offline

---

*Этот файл является частью декомпозированной документации по offline-установке Kubespray.*
