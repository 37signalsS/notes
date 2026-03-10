# Kubespray: Развертывание HA-кластера

Индекс документов по развертыванию HA-кластера Kubernetes с помощью Kubespray.

## Документы

| Документ | Описание |
| :--- | :--- |
| **[Основные концепции](./kubespray_ha_concepts.md)** | Определения, архитектура HA через Keepalived + HAProxy, отличия от ручного kubeadm |
| **[Развертывание HA-кластера](./kubespray_ha_deployment.md)** | Инфраструктурные требования, inventory, переменные, развертывание, проверка |
| **[Дополнительные темы](./kubespray_ha_advanced.md)** | Тестирование отказоустойчивости, конфигурационные файлы, troubleshooting |

## Связанные документы

- **[Kubespray: Обзор](../overview.md)** — общая информация
- **[Kubespray: Установка](../kubespray_install/basic_concepts.md)** — базовая установка
- **[HA с kubeadm](../../kubeadm/ha_keepalived_haproxy/ha_concepts.md)** — ручная настройка HA
- **[Keepalived обзор](../../../../Networking/ServicesAndTools/keepalived_overview.md)** — детали Keepalived
- **[HAProxy обзор](../../../../WebServers/Haproxy/haproxy_overview.md)** — детали HAProxy

## Внешние ресурсы

- **Kubespray Documentation:** [kubespray.io](https://kubespray.io/)
- **GitHub:** [kubernetes-sigs/kubespray](https://github.com/kubernetes-sigs/kubespray)
- **VRRP RFC:** [RFC 5798](https://datatracker.ietf.org/doc/html/rfc5798)
