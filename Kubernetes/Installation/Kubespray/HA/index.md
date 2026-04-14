# Kubespray: Развертывание HA-кластера

Индекс документов по развертыванию HA-кластера Kubernetes с помощью Kubespray.

## Definitions

**HA-кластер (High Availability)** — кластер Kubernetes с несколькими узлами Control Plane для устранения единой точки отказа (SPoF).

**Kubespray HA** — автоматизированное развертывание HA-кластера через Ansible с использованием Keepalived + HAProxy.

## Basic Concepts

### Документы

| Документ | Описание |
| :--- | :--- |
| **[Основные концепции](./kubespray_ha_concepts.md)** | Определения, архитектура HA через Keepalived + HAProxy, отличия от ручного kubeadm |
| **[Развертывание HA-кластера](./kubespray_ha_deployment.md)** | Инфраструктурные требования, inventory, переменные, развертывание, проверка |
| **[Дополнительные темы](./kubespray_ha_advanced.md)** | Тестирование отказоустойчивости, конфигурационные файлы, troubleshooting |

## Practical Scenarios

Практическое руководство по развертыванию — в [kubespray_ha_deployment.md](./kubespray_ha_deployment.md).

## Additional Information

**См. также:** [обзор Kubespray](../overview.md), [базовая установка](../kubespray_install/basic_concepts.md), [ручная настройка HA с kubeadm](../../kubeadm/ha_concepts.md), [развертывание в закрытом контуре](../offline_installation/offline_definitions.md).

**Внешние ресурсы:** [документация Kubespray](https://kubespray.io/), [GitHub](https://github.com/kubernetes-sigs/kubespray), [VRRP RFC 5798](https://datatracker.ietf.org/doc/html/rfc5798).
